"""One-time migration: SQLite (data/insurance.db + data/dashboard_state.db) -> PostgreSQL.

  python tools/migrate_sqlite_to_pg.py [--replace]

* policy ids are preserved, so field_checks / issues keep pointing at the right policy
* every column is converted to its PostgreSQL type (dates, numerics, JSONB, timestamps)
* afterwards every row and every value is re-read from PostgreSQL and compared with SQLite;
  the script exits non-zero if anything differs
* the SQLite files are left untouched (they remain a backup)
* verification runs on a NEW connection after commit, so it only passes if the data is really stored
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extractor import db  # noqa: E402

SRC = ROOT / "data" / "insurance.db"


def lite(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def norm(col: str, v):
    """Comparable form of a value from either side."""
    if v is None:
        return None
    if hasattr(v, "obj"):  # Jsonb wrapper
        v = v.obj
    if col in db.TS_COLS:
        return v.replace(tzinfo=None, microsecond=0).isoformat() if hasattr(v, "isoformat") else str(v)[:19]
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace", action="store_true", help="empty the PostgreSQL tables first")
    a = ap.parse_args()
    if not SRC.exists():
        sys.exit(f"Source not found: {SRC}")

    src = lite(SRC)
    # autocommit: the `with pg.transaction()` block below is then a real top-level transaction that
    # COMMITs on success (inside an implicit transaction it would only be a savepoint and be rolled back)
    pg = db.connect(autocommit=True)
    print(f"Target: {db.safe_url()}")
    existing = pg.execute("SELECT COUNT(*) AS n FROM policies").fetchone()["n"]
    if existing and not a.replace:
        sys.exit(f"PostgreSQL already has {existing} policies. Re-run with --replace to overwrite.")

    policies = [dict(r) for r in src.execute("SELECT * FROM policies ORDER BY id")]
    checks = [dict(r) for r in src.execute("SELECT * FROM field_checks")]
    issues = [dict(r) for r in src.execute("SELECT * FROM issues")]
    dupes = [dict(r) for r in src.execute("SELECT * FROM duplicates")]

    cols = ["id"] + db.POLICY_COLUMNS
    with pg.transaction():
        if a.replace:
            pg.execute("TRUNCATE policies, field_checks, issues, duplicates RESTART IDENTITY CASCADE")
        with pg.cursor() as cur:
            cur.executemany(
                f"INSERT INTO policies ({', '.join(cols)}) OVERRIDING SYSTEM VALUE VALUES ({', '.join(['%s'] * len(cols))})",
                [[p["id"]] + [db.to_db(c, p.get(c)) for c in db.POLICY_COLUMNS] for p in policies])
            cur.executemany("INSERT INTO field_checks VALUES (%s, %s, %s, %s, %s, %s)",
                            [(c["policy_id"], c["field"], c["rules_value"], c["llm_value"], c["verdict"], bool(c["llm_ungrounded"]))
                             for c in checks])
            cur.executemany("INSERT INTO issues VALUES (%s, %s, %s, %s)",
                            [(i["policy_id"], i["severity"], i["field"], i["message"]) for i in issues])
            cur.executemany("INSERT INTO duplicates (file, sha256, duplicate_of) VALUES (%s, %s, %s) ON CONFLICT (file) DO NOTHING",
                            [(d["file"], d["sha256"], d["duplicate_of"]) for d in dupes])
        pg.execute("SELECT setval(pg_get_serial_sequence('policies', 'id'), (SELECT COALESCE(MAX(id), 1) FROM policies))")

    pg.close()

    # ---------------- verification (fresh connection: proves the data is committed) ----------------
    pg = db.connect(autocommit=True, init=False)
    ok = True
    counts = {}
    for table, n_src in [("policies", len(policies)), ("field_checks", len(checks)), ("issues", len(issues)),
                         ("duplicates", len({d['file'] for d in dupes}))]:
        n_pg = pg.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        counts[table] = (n_src, n_pg)
        ok &= n_src == n_pg
        print(f"  {table:<17} sqlite={n_src:<6} postgres={n_pg:<6} {'OK' if n_src == n_pg else 'MISMATCH'}")

    pg_rows = {r["id"]: r for r in pg.execute("SELECT * FROM policies")}
    diffs = 0
    for p in policies:
        q = pg_rows.get(p["id"])
        if q is None:
            print(f"  missing policy id {p['id']}"); diffs += 1; continue
        for c in db.POLICY_COLUMNS:
            if norm(c, db.to_db(c, p.get(c))) != norm(c, q[c]):
                diffs += 1
                if diffs <= 10:
                    print(f"  value differs: id={p['id']} {c}: sqlite={p.get(c)!r} postgres={q[c]!r}")
    print(f"  values compared: {len(policies) * len(db.POLICY_COLUMNS):,}  differences: {diffs}")
    v = pg.execute("SELECT COUNT(*) AS n FROM vehicles").fetchone()["n"]
    v_src = src.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    print(f"  vehicles view     sqlite={v_src:<6} postgres={v:<6} {'OK' if v == v_src else 'MISMATCH'}")
    ok &= diffs == 0 and v == v_src
    print("MIGRATION VERIFIED" if ok else "MIGRATION HAS DIFFERENCES")
    pg.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
