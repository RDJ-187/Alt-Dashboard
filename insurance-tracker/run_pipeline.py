"""Insurance extraction pipeline.

  python run_pipeline.py --root "<pdf folder>"            rules + validation -> SQLite (seconds)
  python run_pipeline.py --root "<pdf folder>" --llm      + local LLM cross-check (slow, resumable)
  python run_pipeline.py --root ... --llm --limit 5       try the LLM on a few files first
  python run_pipeline.py --root ... --llm --cache-only    re-score using LLM results already computed

Re-running is always safe: unchanged PDFs reuse cached results; new PDFs are added.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from extractor import db
from extractor.pdfdoc import PdfDoc
from extractor.reconcile import reconcile
from extractor.rules_stage import extract_file


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="folder containing policy PDFs (searched recursively)")
    ap.add_argument("--llm", action="store_true", help="run the local LLM cross-check")
    ap.add_argument("--cache-only", action="store_true", help="LLM: use cached results only, never call the model")
    ap.add_argument("--limit", type=int, default=0, help="LLM: process at most N uncached files this run")
    args = ap.parse_args()

    root = Path(args.root)
    pdfs = sorted(root.rglob("*.pdf"))
    con = db.connect()
    llm_mod = None
    if args.llm:
        from extractor import llm_stage as llm_mod

    seen: dict[str, str] = {}
    stats = Counter()
    llm_done = 0
    t_start = time.time()
    for i, pdf in enumerate(pdfs, 1):
        rec = extract_file(pdf, root)
        sha = rec["sha256"]
        if sha in seen:
            con.execute("INSERT INTO duplicates VALUES (?,?,?)", (sha, rec["file"], seen[sha]))
            stats["duplicate_file"] += 1
            continue
        seen[sha] = rec["file"]

        llm = None
        if llm_mod:
            cached = (llm_mod.OUT / llm_mod.MODEL.replace(":", "_") / f"{sha[:16]}.json").exists()
            if cached or (not args.cache_only and (not args.limit or llm_done < args.limit)):
                try:
                    llm = llm_mod.extract(PdfDoc(pdf))
                    if not cached:
                        llm_done += 1
                        el = time.time() - t_start
                        print(f"  [{i}/{len(pdfs)}] LLM {llm['seconds']:>6.1f}s  {rec['file'][-40:]}"
                              f"  ungrounded={llm['ungrounded']}  elapsed={el/60:.1f}m", flush=True)
                except Exception as ex:
                    print(f"  LLM failed on {rec['file']}: {ex!r}", file=sys.stderr)
        rc = reconcile(rec, llm)
        db.save(con, rec, rc)
        con.commit()
        stats[rc["status"]] += 1
        stats["llm_checked" if llm else "rules_only"] += 1

    con.execute("DELETE FROM duplicates WHERE rowid NOT IN (SELECT MIN(rowid) FROM duplicates GROUP BY file)")
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
    print(f"\nPDFs scanned: {len(pdfs)}  unique policies in DB: {total}  stats: {dict(stats)}")
    print(f"Database: {db.DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
