"""Policy upload: stage PDFs, classify them against the database, then import on confirmation.

Flow
  1. upload   each PDF is saved to data/inbox/<batch>/ and run through the rules extractor
  2. review   every file gets an outcome (see OUTCOMES); nothing is written to the database yet
  3. import   selected files are re-checked against the live database, saved, and the PDF is
              moved to data/uploads/<date>/ so the dashboard can open it later

A newer policy needs no special handling in the database: the `vehicles` view always shows the policy
with the latest OD end date per chassis, so the new policy becomes current, the old one stays as
history, and expiry alerts keyed on the old end date close by themselves.
"""
from __future__ import annotations

import re
import shutil
import threading
from datetime import date
from pathlib import Path

from extractor import db
from extractor.reconcile import reconcile
from extractor.rules_stage import extract_file

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INBOX = DATA / "inbox"
UPLOADS = DATA / "uploads"
MAX_BYTES = 30 * 1024 * 1024
BATCH_RX = re.compile(r"^[0-9a-f-]{36}$")

# outcome -> (label, importable)
OUTCOMES = {
    "new": ("New vehicle", True),
    "newer": ("Newer policy", True),
    "history": ("Older policy", True),
    "duplicate": ("Already in system", False),
    "same_policy": ("Same policy number", False),
    "batch_duplicate": ("Duplicate in this upload", False),
    "error": ("Needs attention", False),
}

_lock = threading.Lock()
_batches: dict[str, dict[str, dict]] = {}  # batch id -> sha256 -> staged item


def reset_inbox() -> None:
    """Staged files only live for one server session."""
    shutil.rmtree(INBOX, ignore_errors=True)


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9 ._()\-]", "_", base).strip(" .") or "policy.pdf"
    return base if base.lower().endswith(".pdf") else base + ".pdf"


def _brief(rec: dict) -> dict:
    f = rec.get("fields") or {}
    g = lambda k: (f.get(k).isoformat() if isinstance(f.get(k), date) else f.get(k))
    return {k: g(k) for k in ("insurer", "policy_no", "registration_no", "chassis_no", "engine_no", "oem", "model",
                              "od_start", "od_end", "city_clean", "insured_name", "fire_covered", "chassis_damage_covered")}


def _classify(con, rec: dict) -> dict:
    """Outcome of one extracted record against the live database."""
    f = rec.get("fields") or {}
    errors = [i["message"] for i in rec.get("issues", []) if i["severity"] == "error"]
    warnings = [i["message"] for i in rec.get("issues", []) if i["severity"] != "error"]
    res = {"errors": errors, "warnings": warnings, "current": None, "changes": []}
    if errors or not f.get("chassis_no") or not f.get("od_end"):
        if not errors:
            res["errors"] = ["chassis number or policy end date could not be read"]
        return {**res, "outcome": "error"}

    same_file = con.execute("SELECT id FROM policies WHERE sha256 = %s", (rec["sha256"],)).fetchone()
    if same_file:
        return {**res, "outcome": "duplicate", "existing_id": same_file["id"]}
    same_pol = con.execute("SELECT id, file FROM policies WHERE policy_no = %s AND insurer = %s",
                           (f.get("policy_no"), f.get("insurer"))).fetchone()
    if same_pol:
        return {**res, "outcome": "same_policy", "existing_id": same_pol["id"]}

    cur = con.execute("SELECT id, policy_no, insurer, od_start, od_end, registration_no FROM vehicles WHERE chassis_no = %s",
                      (f["chassis_no"],)).fetchone()
    if not cur:
        return {**res, "outcome": "new"}
    new_end = f["od_end"] if isinstance(f["od_end"], date) else date.fromisoformat(str(f["od_end"]))
    res["current"] = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in cur.items()}
    if new_end > cur["od_end"]:
        if cur["insurer"] != f.get("insurer"):
            res["changes"].append(f"Insurer changes from {cur['insurer']} to {f.get('insurer')}")
        new_reg, old_reg = f.get("registration_no"), cur["registration_no"]
        if new_reg and new_reg != old_reg:
            res["changes"].append(f"Registration added: {new_reg}" if not old_reg
                                  else f"Registration changes from {old_reg} to {new_reg}")
        return {**res, "outcome": "newer"}
    return {**res, "outcome": "history"}


def stage(batch: str, name: str, data: bytes) -> dict:
    """Save one uploaded PDF into the batch inbox, extract and classify it."""
    if not BATCH_RX.match(batch):
        raise ValueError("invalid batch id")
    display = name.replace("\\", "/")[-300:]
    problem = ("file is larger than 30 MB" if len(data) > MAX_BYTES
               else "not a valid PDF file" if not data.startswith(b"%PDF") else None)
    if problem:  # listed in the review so the user sees why it was not accepted
        item = {"name": display, "sha256": None, "outcome": "error", "fields": {}, "errors": [problem],
                "warnings": [], "current": None, "changes": []}
        with _lock:
            _batches.setdefault(batch, {})[f"bad-{len(_batches.get(batch, {}))}-{display}"] = item
        return public(item)
    folder = INBOX / batch
    folder.mkdir(parents=True, exist_ok=True)
    fname = _safe_name(display)
    path = folder / fname
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{Path(fname).stem} ({n}).pdf"
    path.write_bytes(data)
    try:
        rec = extract_file(path, folder)
    except Exception as ex:  # noqa: BLE001 - an unreadable PDF must not stop the batch
        rec = {"sha256": None, "fields": {}, "issues": [{"severity": "error", "field": "_file", "message": f"could not read PDF ({ex.__class__.__name__})"}]}
    with db.connect(autocommit=True, init=False) as con:
        res = _classify(con, rec)
    item = {"name": display, "stored": path.name, "sha256": rec.get("sha256"), "rec": rec,
            "fields": _brief(rec), **res}
    key = rec.get("sha256") or f"err-{path.name}"
    with _lock:
        b = _batches.setdefault(batch, {})
        if key in b:  # identical file twice in one upload
            item["outcome"] = "batch_duplicate"
            key = f"{key}-{path.name}"
        b[key] = item
    return public(item)


def _relabel(items: list[dict]) -> None:
    """Several policies for one chassis in the same upload: only the latest can be the current one."""
    by_chassis: dict[str, list[dict]] = {}
    for it in items:
        if it["outcome"] in ("new", "newer", "history"):
            by_chassis.setdefault(it["fields"]["chassis_no"], []).append(it)
    for group in by_chassis.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda it: it["fields"]["od_end"])
        latest = group[-1]
        for it in group[:-1]:
            it["outcome"] = "history"
            it.setdefault("warnings", []).append("A later policy for this vehicle is in the same upload")
        if latest["outcome"] == "history" and not latest.get("current"):
            latest["outcome"] = "new"


def public(item: dict) -> dict:
    label, importable = OUTCOMES[item["outcome"]]
    return {k: item.get(k) for k in ("name", "sha256", "outcome", "fields", "errors", "warnings", "current", "changes")} | \
        {"label": label, "importable": importable, "key": item.get("sha256")}


def summary(batch: str) -> dict:
    with _lock:
        items = list(_batches.get(batch, {}).values())
    _relabel(items)
    return {"batch": batch, "items": [public(i) for i in items]}


def discard(batch: str) -> None:
    if not BATCH_RX.match(batch):
        raise ValueError("invalid batch id")
    with _lock:
        _batches.pop(batch, None)
    shutil.rmtree(INBOX / batch, ignore_errors=True)


def commit(batch: str, keys: list[str]) -> dict:
    """Import the selected staged files. Each one is re-classified against the live database first."""
    if not BATCH_RX.match(batch):
        raise ValueError("invalid batch id")
    with _lock:
        staged = dict(_batches.get(batch, {}))
    chosen = [staged[k] for k in keys if k in staged]
    chosen.sort(key=lambda it: str(it["fields"].get("od_end") or ""))  # oldest first: the latest ends up current
    today = date.today().isoformat()
    dest_dir = UPLOADS / today
    results, moves = [], []
    with db.connect() as con:
        with con.transaction():
            for it in chosen:
                rec = it["rec"]
                res = _classify(con, rec)
                outcome = res["outcome"]
                if not OUTCOMES[outcome][1]:
                    results.append({"name": it["name"], "outcome": outcome, "label": OUTCOMES[outcome][0], "imported": False})
                    continue
                target = dest_dir / it["stored"]
                if target.exists() or any(m[1] == target for m in moves):
                    target = dest_dir / f"{Path(it['stored']).stem} [{rec['sha256'][:8]}].pdf"
                rec = {**rec, "file": f"uploads/{today}/{target.name}", "source_folder": f"Uploaded {today}"}
                pid = db.save(con, rec, reconcile(rec, None))
                con.execute("INSERT INTO import_log (batch, file_name, sha256, outcome, policy_id, chassis_no, od_end) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (batch, it["name"], rec["sha256"], outcome, pid, rec["fields"].get("chassis_no"),
                             db.to_db("od_end", rec["fields"].get("od_end"))))
                moves.append((INBOX / batch / it["stored"], target))
                results.append({"name": it["name"], "outcome": outcome, "label": OUTCOMES[outcome][0],
                                "imported": True, "policy_id": pid})
    # files are moved only after the database commit succeeded
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src, dst in moves:
        shutil.move(str(src), str(dst))
    discard(batch)
    counts: dict[str, int] = {}
    for r in results:
        if r["imported"]:
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return {"imported": sum(r["imported"] for r in results), "skipped": sum(not r["imported"] for r in results),
            "by_outcome": counts, "results": results}


def recent(limit: int = 30) -> list[dict]:
    with db.connect(autocommit=True, init=False) as con:
        return con.execute(
            "SELECT l.imported_at, l.file_name, l.outcome, l.policy_id, l.od_end, p.registration_no, p.chassis_no, p.insurer "
            "FROM import_log l LEFT JOIN policies p ON p.id = l.policy_id ORDER BY l.imported_at DESC, l.id DESC LIMIT %s",
            (limit,)).fetchall()


def resolve_upload(rel: str) -> Path | None:
    """Absolute path of an uploaded PDF stored as 'uploads/<date>/<name>'."""
    p = (DATA / rel.replace("\\", "/")).resolve()
    return p if UPLOADS.resolve() in p.parents and p.is_file() else None

