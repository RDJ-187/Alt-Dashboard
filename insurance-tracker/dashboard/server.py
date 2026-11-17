"""Policy Tracker dashboard server: Python standard library HTTP server + PostgreSQL (psycopg 3).

  python dashboard/server.py [--port 8050] [--asof YYYY-MM-DD]

Reads   policies / vehicles / field_checks / issues      (extraction output)
Writes  renewal_tracking / alert_reads                   (dashboard state; never touched by re-extraction)
Serves  dashboard/static/*                               (single-page app)
Connection: DATABASE_URL from the environment or insurance-tracker/.env
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from extractor import db  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
PDF_ROOT = Path(os.environ.get("INS_PDF_ROOT", ROOT.parent / "OneDrive_2026-11-14" / "HR Assignment")).resolve()

RENEWAL_STATES = {"not_started", "in_progress", "renewed", "lapsed"}

LIST_COLUMNS = [
    "id", "status", "insurer", "policy_no", "policy_type", "od_start", "od_end", "tp_end",
    "registration_no", "chassis_no", "engine_no", "make", "oem", "model", "vehicle_class",
    "year_of_manufacture", "insured_name", "city_clean", "state", "financier",
    "fire_covered", "chassis_damage_covered", "source_folder",
]

ASOF: date | None = None  # fixed "today" for demos; None = real date


def today() -> date:
    return ASOF or date.today()


def conn():
    """Short-lived autocommit connection per request (local server, low traffic)."""
    return db.connect(autocommit=True, init=False)


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return str(v)


def api_vehicles(_q) -> dict:
    with conn() as con:
        rows = con.execute(f"SELECT {', '.join(LIST_COLUMNS)} FROM vehicles ORDER BY od_end").fetchall()
        meta = con.execute("SELECT MAX(extracted_at) AS updated, COUNT(*) AS n, "
                           "COUNT(llm_agreement) AS llm FROM policies").fetchone()
        dupes = con.execute("SELECT COUNT(*) AS n FROM duplicates").fetchone()["n"]
        tracking = {r["chassis_no"]: r for r in con.execute("SELECT * FROM renewal_tracking")}
        reads = [r["key"] for r in con.execute("SELECT key FROM alert_reads")]
    for r in rows:
        t = tracking.get(r["chassis_no"])
        # a manual mark applies only to the policy term it was made for; a newer policy resets it
        r["renewal"] = t if t and t["od_end"] == r["od_end"] else None
    return {"asof": today().isoformat(), "updated": meta["updated"], "policies": meta["n"], "llm_checked": meta["llm"],
            "duplicates": dupes, "vehicles": rows, "alert_reads": reads}


def api_vehicle(pid: int) -> dict | None:
    with conn() as con:
        rec = con.execute("SELECT * FROM policies WHERE id = %s", (pid,)).fetchone()
        if not rec:
            return None
        rec["history"] = con.execute(
            "SELECT id, policy_no, insurer, od_start, od_end FROM policies WHERE chassis_no = %s AND id <> %s "
            "ORDER BY od_end DESC", (rec["chassis_no"], pid)).fetchall()
        rec["issues"] = con.execute("SELECT severity, field, message FROM issues WHERE policy_id = %s", (pid,)).fetchall()
        rec["checks"] = con.execute(
            "SELECT field, rules_value, llm_value, verdict FROM field_checks WHERE policy_id = %s", (pid,)).fetchall()
        t = con.execute("SELECT * FROM renewal_tracking WHERE chassis_no = %s", (rec["chassis_no"],)).fetchone()
    rec["renewal"] = t if t and t["od_end"] == rec["od_end"] else None
    rec["has_pdf"] = _pdf_path(rec["file"]) is not None
    return rec


def _pdf_path(rel: str | None) -> Path | None:
    if not rel:
        return None
    if rel.replace("\\", "/").startswith("uploads/"):
        return ingest.resolve_upload(rel)
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
        self._send(code, json.dumps(obj, ensure_ascii=False, default=_jsonable).encode("utf-8"), "application/json; charset=utf-8")

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
            if parts[:3] == ["api", "import", "batch"] and len(parts) == 4:
                return self._json(ingest.summary(parts[3]))
            if parts[:3] == ["api", "import", "recent"]:
                return self._json(ingest.recent())
            if parts[:2] == ["api", "pdf"] and len(parts) == 3 and parts[2].isdigit():
                with conn() as con:
                    row = con.execute("SELECT file FROM policies WHERE id = %s", (int(parts[2]),)).fetchone()
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
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        try:
            if parts == ["api", "import", "upload"]:  # raw PDF bytes, not JSON
                q = parse_qs(u.query)
                n = int(self.headers.get("Content-Length") or 0)
                if n > ingest.MAX_BYTES + 1024:
                    self.rfile.read(n)
                    return self._json({"error": "file is larger than 30 MB"}, 413)
                data = self.rfile.read(n)
                return self._json(ingest.stage(q.get("batch", [""])[0], q.get("name", ["policy.pdf"])[0], data))
            body = self._body()
            if parts == ["api", "import", "commit"]:
                return self._json(ingest.commit(str(body.get("batch", "")), [str(k) for k in body.get("keys", [])][:5000]))
            if parts == ["api", "import", "discard"]:
                ingest.discard(str(body.get("batch", "")))
                return self._json({"ok": True})
            now = datetime.now().astimezone()
            if parts == ["api", "alerts", "read"]:
                keys = [str(k)[:200] for k in body.get("keys", [])][:5000]
                with conn() as con, con.cursor() as cur:
                    cur.executemany("INSERT INTO alert_reads (key, read_at) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                                    [(k, now) for k in keys])
                return self._json({"ok": True, "marked": len(keys)})
            if parts == ["api", "renewal"]:
                chassis = str(body.get("chassis_no") or "")[:40]
                st = body.get("status")
                if not chassis or st not in RENEWAL_STATES:
                    return self._json({"error": "chassis_no and a valid status are required"}, 400)
                note = (body.get("note") or "")[:1000]
                od_end = date.fromisoformat(str(body["od_end"])[:10]) if body.get("od_end") else None
                with conn() as con:
                    if st == "not_started" and not note:
                        con.execute("DELETE FROM renewal_tracking WHERE chassis_no = %s", (chassis,))
                    else:
                        con.execute("INSERT INTO renewal_tracking (chassis_no, od_end, status, note, updated_at) "
                                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (chassis_no) DO UPDATE SET "
                                    "od_end = EXCLUDED.od_end, status = EXCLUDED.status, note = EXCLUDED.note, "
                                    "updated_at = EXCLUDED.updated_at", (chassis, od_end, st, note, now))
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
    try:
        with db.connect(autocommit=True) as con:  # also creates any missing tables
            n = con.execute("SELECT COUNT(*) AS n FROM policies").fetchone()["n"]
    except Exception as ex:  # noqa: BLE001
        sys.exit(f"Cannot reach PostgreSQL at {db.safe_url()}: {ex}\nStart it with: docker compose up -d")
    if not n:
        print("Warning: the policies table is empty. Run run_pipeline.py first.")
    ingest.reset_inbox()
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Policy Tracker running at http://{a.host}:{a.port}  (as of {today()}, {n} policies, {db.safe_url()})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
