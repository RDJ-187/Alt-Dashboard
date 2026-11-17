"""SQLite storage. One file, zero setup; the dashboard reads from it.

Tables
  policies      one row per unique PDF (by SHA-256) with every extracted field
  field_checks  per-field audit trail: rules value, LLM value, verdict
  issues        validation warnings / errors per policy
View
  vehicles      latest policy per chassis number (what the tracker shows)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path("data/insurance.db")

POLICY_COLUMNS = [
    "sha256", "file", "source_folder", "pages", "status", "llm_agreement", "review_reasons",
    "insurer", "product", "policy_type", "policy_no", "legacy_policy_no", "issue_date",
    "od_start", "od_end", "tp_start", "tp_end", "tp_policy_no", "tp_insurer", "next_renewal_date",
    "registration_no", "registration_no_filename", "registration_date", "chassis_no", "engine_no",
    "make", "oem", "model", "vehicle_class", "body_type", "carrier_type", "vehicle_usage", "fuel_type",
    "year_of_manufacture", "cubic_capacity",
    "insured_name", "city", "city_clean", "state", "hypothecation", "financier",
    "idv", "od_premium", "od_base_premium", "tp_premium", "total_premium", "ncb_percent",
    "compulsory_deductible", "fire_total_loss_excess", "addons",
    "fire_covered", "fire_note", "fire_exclusion_text", "chassis_damage_covered", "chassis_damage_causes",
    "previous_policy_no", "previous_insurer", "previous_policy_type", "previous_policy_start", "previous_policy_end",
    "extracted_at",
]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS policies (
  id INTEGER PRIMARY KEY,
  {", ".join(f'"{c}" TEXT' if c != "sha256" else '"sha256" TEXT UNIQUE NOT NULL' for c in POLICY_COLUMNS)}
);
CREATE TABLE IF NOT EXISTS field_checks (
  policy_id INTEGER REFERENCES policies(id) ON DELETE CASCADE,
  field TEXT, rules_value TEXT, llm_value TEXT, verdict TEXT, llm_ungrounded INTEGER
);
CREATE TABLE IF NOT EXISTS issues (
  policy_id INTEGER REFERENCES policies(id) ON DELETE CASCADE,
  severity TEXT, field TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS duplicates (sha256 TEXT, file TEXT, duplicate_of TEXT);
CREATE INDEX IF NOT EXISTS ix_pol_chassis ON policies(chassis_no);
CREATE INDEX IF NOT EXISTS ix_pol_end ON policies(od_end);
DROP VIEW IF EXISTS vehicles;
CREATE VIEW vehicles AS
  SELECT p.* FROM policies p
  WHERE p.id = (SELECT p2.id FROM policies p2 WHERE p2.chassis_no = p.chassis_no
                ORDER BY p2.od_end DESC, p2.id DESC LIMIT 1);
"""


def _cell(v):
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def save(con: sqlite3.Connection, rec: dict, rc: dict) -> None:
    f = dict(rec["fields"])
    row = {**f, "sha256": rec["sha256"], "file": rec["file"], "source_folder": rec["source_folder"],
           "pages": rec.get("pages"), "status": rc["status"], "llm_agreement": rc["llm_agreement"],
           "review_reasons": rc["review_reasons"], "extracted_at": datetime.now().isoformat(timespec="seconds")}
    cols = ", ".join(f'"{c}"' for c in POLICY_COLUMNS)
    marks = ", ".join("?" for _ in POLICY_COLUMNS)
    upd = ", ".join(f'"{c}"=excluded."{c}"' for c in POLICY_COLUMNS if c != "sha256")
    con.execute(f"INSERT INTO policies ({cols}) VALUES ({marks}) ON CONFLICT(sha256) DO UPDATE SET {upd}",
                [_cell(row.get(c)) for c in POLICY_COLUMNS])
    pid = con.execute("SELECT id FROM policies WHERE sha256=?", (rec["sha256"],)).fetchone()[0]
    con.execute("DELETE FROM field_checks WHERE policy_id=?", (pid,))
    con.execute("DELETE FROM issues WHERE policy_id=?", (pid,))
    con.executemany("INSERT INTO field_checks VALUES (?,?,?,?,?,?)",
                    [(pid, c["field"], _cell(c["rules"]), _cell(c["llm"]), c["verdict"], int(c.get("llm_ungrounded", False)))
                     for c in rc["checks"]])
    con.executemany("INSERT INTO issues VALUES (?,?,?,?)",
                    [(pid, i["severity"], i["field"], i["message"]) for i in rec["issues"]])
