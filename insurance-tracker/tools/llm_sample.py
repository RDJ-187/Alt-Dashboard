"""Run the LLM stage on N files per insurer and show rules-vs-LLM verdicts (benchmark + sanity check).

  python tools/llm_sample.py --root "<pdf folder>" [--per-insurer 1]
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extractor import llm_stage  # noqa: E402
from extractor.pdfdoc import PdfDoc  # noqa: E402
from extractor.reconcile import reconcile  # noqa: E402
from extractor.rules_stage import extract_file  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--per-insurer", type=int, default=1)
a = ap.parse_args()
root = Path(a.root)

picked = defaultdict(list)
for row in csv.DictReader(open("data/census.csv", encoding="utf-8")):
    if len(picked[row["insurer"]]) < a.per_insurer:
        picked[row["insurer"]].append(root / row["file"])

print(f"model: {llm_stage.MODEL}")
for ins, files in picked.items():
    for pdf in files:
        rec = extract_file(pdf, root)
        llm = llm_stage.extract(PdfDoc(pdf))
        rc = reconcile(rec, llm)
        print(f"\n### {ins}  {pdf.name}  {llm['seconds']}s  prompt={llm['prompt_tokens']} out={llm['output_tokens']}"
              f"  agreement={rc['llm_agreement']}  status={rc['status']}")
        for c in rc["checks"]:
            if c["verdict"] != "agree":
                print(f"   {c['verdict']:11s} {c['field']:16s} rules={c['rules']!r:40s} llm={c['llm']!r}"
                      + ("  [UNGROUNDED]" if c.get("llm_ungrounded") else ""))
