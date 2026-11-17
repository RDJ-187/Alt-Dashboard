"""Run the rules stage over the corpus and print fill-rate + issue report."""
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extractor.rules_stage import run  # noqa: E402

FIELDS = ["insurer", "policy_no", "registration_no", "chassis_no", "engine_no", "make", "model",
          "insured_name", "city", "od_start", "od_end", "tp_start", "tp_end", "idv", "od_premium",
          "tp_premium", "total_premium", "ncb_percent", "hypothecation", "addons", "policy_type",
          "fire_covered", "chassis_damage_covered", "year_of_manufacture", "vehicle_class"]

recs = run(sys.argv[1])
by_ins = defaultdict(list)
for r in recs:
    by_ins[r["fields"].get("insurer", "UNKNOWN")].append(r)

print(f"{'field':24s}" + "".join(f"{k[:14]:>16s}" for k in by_ins))
for fld in FIELDS:
    row = f"{fld:24s}"
    for ins, rs in by_ins.items():
        n = sum(1 for r in rs if r["fields"].get(fld) not in (None, "", []))
        row += f"{n:>10d}/{len(rs):<5d}"
    print(row)

print("\nIssues (severity, field, message-prefix):")
c = Counter((i["severity"], i["field"], i["message"][:70]) for r in recs for i in r["issues"])
for (sev, fld, msg), n in c.most_common(60):
    print(f"{n:4d}  {sev:7s} {fld:18s} {msg}")
ok = sum(1 for r in recs if not any(i["severity"] == "error" for i in r["issues"]))
print(f"\nRecords with zero errors: {ok}/{len(recs)}")
