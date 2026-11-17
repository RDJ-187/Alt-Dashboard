"""Policy Tracker dashboard server - Python standard library only, runs fully offline.

  python dashboard/server.py [--port 8050] [--asof YYYY-MM-DD]

Reads   data/insurance.db          (extraction output; read-only here)
Writes  data/dashboard_state.db    (renewal tracking + alert read state; kept separate so the
                                    extraction DB can be rebuilt at any time without losing it)
Serves  dashboard/static/*         (single-page app)
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
import sys
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DB = ROOT / "data" / "insurance.db"
STATE_DB = ROOT / "data" / "dashboard_state.db"
PDF_ROOT = Path(os.environ.get("INS_PDF_ROOT", ROOT.parent / "OneDrive_2026-11-14" / "HR Assignment")).resolve()

RENEWAL_STATES = {"not_started", "in_progress", "renewed", "lapsed"}

LIST_COLUMNS = [
    "id", "status", "insurer", "policy_no", "policy_type", "od_start", "od_end", "tp_end",
    "registration_no", "chassis_no", "engine_no", "make", "oem", "model", "vehicle_class",
    "year_of_manufacture", "insured_name", "city_clean", "state", "financier",
    "fire_covered", "chassis_damage_covered", "source_folder",
]
JSON_COLUMNS = {"addons", "chassis_damage_causes", "review_reasons"}

ASOF: date | None = None  # fixed "today" for demos; None = real date


def today() -> date:
    return ASOF or date.today()


def ro() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def state() -> sqlite3.Connection:
    con = sqlite3.connect(STATE_DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS renewal_tracking (
          chassis_no TEXT PRIMARY KEY, od_end TEXT, status TEXT NOT NULL, note TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS alert_reads (key TEXT PRIMARY KEY, read_at TEXT NOT NULL);
    """)
    return con


def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in JSON_COLUMNS & d.keys():
        if d[k]:
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def api_vehicles(_q) -> dict:
    with ro() as con:
        rows = [dict(r) for r in con.execute(f"SELECT {', '.join(LIST_COLUMNS)} FROM vehicles ORDER BY od_end")]
        meta = con.execute("SELECT MAX(extracted_at) AS updated, COUNT(*) AS n, "
                           "SUM(llm_agreement IS NOT NULL) AS llm FROM policies").fetchone()
        dupes = con.execute("SELECT COUNT(*) FROM duplicates").fetchone()[0]
    with state() as s:
        tracking = {r["chassis_no"]: dict(r) for r in s.execute("SELECT * FROM renewal_tracking")}
        reads = [r["key"] for r in s.execute("SELECT key FROM alert_reads")]
    for r in rows:
        t = tracking.get(r["chassis_no"])
        # a manual mark applies only to the policy term it was made for; a newer policy resets it
        r["renewal"] = t if t and t["od_end"] == r["od_end"] else None
    return {"asof": today().isoformat(), "updated": meta["updated"], "policies": meta["n"], "llm_checked": meta["llm"],
            "duplicates": dupes, "vehicles": rows, "alert_reads": reads}


def api_vehicle(pid: int) -> dict | None:
    with ro() as con:
        row = con.execute("SELECT * FROM policies WHERE id=?", (pid,)).fetchone()
        if not row:
            return None
        rec = _decode(row)
        rec["history"] = [dict(r) for r in con.execute(
            "SELECT id, policy_no, insurer, od_start, od_end FROM policies WHERE chassis_no=? AND id<>? ORDER BY od_end DESC",
            (rec["chassis_no"], pid))]
        rec["issues"] = [dict(r) for r in con.execute("SELECT severity, field, message FROM issues WHERE policy_id=?", (pid,))]
        rec["checks"] = [dict(r) for r in con.execute(
            "SELECT field, rules_value, llm_value, verdict FROM field_checks WHERE policy_id=?", (pid,))]
    with state() as s:
        t = s.execute("SELECT * FROM renewal_tracking WHERE chassis_no=?", (rec["chassis_no"],)).fetchone()
    rec["renewal"] = dict(t) if t and t["od_end"] == rec["od_end"] else None
    rec["has_pdf"] = _pdf_path(rec["file"]) is not None
    return rec


def _pdf_path(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = (PDF_ROOT / rel.replace("\\", "/")).resolve()
    if PDF_ROOT not in p.parents or not p.is_file():
        return None
    return p


class Handler(BaseHTTPRequestHandler):
    server_version = "PolicyTracker/1.0"

    def log_message(self, fmt, *args):  # quiet console: errors only
        if args and str(args[1])[:1] in "45":
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ---- helpers
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- routes
    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        try:
            if parts[:2] == ["api", "vehicles"]:
                return self._json(api_vehicles(parse_qs(u.query)))
            if parts[:2] == ["api", "vehicle"] and len(parts) == 3 and parts[2].isdigit():
                rec = api_vehicle(int(parts[2]))
                return self._json(rec) if rec else self._json({"error": "not found"}, 404)
            if parts[:2] == ["api", "pdf"] and len(parts) == 3 and parts[2].isdigit():
                with ro() as con:
                    row = con.execute("SELECT file FROM policies WHERE id=?", (int(parts[2]),)).fetchone()
                p = _pdf_path(row["file"]) if row else None
                if not p:
                    return self._json({"error": "pdf not found"}, 404)
                return self._send(200, p.read_bytes(), "application/pdf",
                                  {"Content-Disposition": f'inline; filename="{p.name}"'})
            # static files; unknown paths fall back to the app shell (hash routing)
            rel = "/".join(parts) or "index.html"
            f = (STATIC / rel).resolve()
            if STATIC not in f.parents or not f.is_file():
                f = STATIC / "index.html"
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            return self._send(200, f.read_bytes(), ctype)
        except Exception as ex:  # noqa: BLE001 - surface as JSON, keep serving
            return self._json({"error": str(ex)}, 500)

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        try:
            body = self._body()
            now = datetime.now().isoformat(timespec="seconds")
            if parts == ["api", "alerts", "read"]:
                keys = [str(k)[:200] for k in body.get("keys", [])][:5000]
                with state() as s:
                    s.executemany("INSERT OR IGNORE INTO alert_reads VALUES (?,?)", [(k, now) for k in keys])
                return self._json({"ok": True, "marked": len(keys)})
            if parts == ["api", "renewal"]:
                chassis = str(body.get("chassis_no") or "")[:40]
                st = body.get("status")
                if not chassis or st not in RENEWAL_STATES:
                    return self._json({"error": "chassis_no and a valid status are required"}, 400)
                note = (body.get("note") or "")[:1000]
                od_end = str(body.get("od_end") or "")[:10]
                with state() as s:
                    if st == "not_started" and not note:
                        s.execute("DELETE FROM renewal_tracking WHERE chassis_no=?", (chassis,))
                    else:
                        s.execute("INSERT INTO renewal_tracking VALUES (?,?,?,?,?) ON CONFLICT(chassis_no) DO UPDATE "
                                  "SET od_end=excluded.od_end, status=excluded.status, note=excluded.note, "
                                  "updated_at=excluded.updated_at", (chassis, od_end, st, note, now))
                return self._json({"ok": True, "chassis_no": chassis, "od_end": od_end, "status": st,
                                   "note": note, "updated_at": now})
            return self._json({"error": "not found"}, 404)
        except Exception as ex:  # noqa: BLE001
            return self._json({"error": str(ex)}, 400)


def main():
    global ASOF
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--host", default="127.0.0.1")  # local only: the data is private
    ap.add_argument("--asof", help="pretend today is this date (YYYY-MM-DD)")
    a = ap.parse_args()
    if a.asof:
        ASOF = date.fromisoformat(a.asof)
    if not DB.exists():
        sys.exit(f"Database not found: {DB}. Run run_pipeline.py first.")
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Policy Tracker running at http://{a.host}:{a.port}  (as of {today()})  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
