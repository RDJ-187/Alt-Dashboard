"""Stage 1: deterministic extraction (layout + rules) for every PDF.

Output: data/extracted/rules/<sha16>.json  (fields, alternate readings, issues)
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import parsers
from .common import REG_RX
from .coverage import derive
from .normalize import normalize
from .pdfdoc import PdfDoc
from .validate import validate

OUT = Path("data/extracted/rules")


def _json_default(o):
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o))


def extract_file(pdf: Path, root: Path) -> dict:
    doc = PdfDoc(pdf)
    rel = str(pdf.relative_to(root))
    rec = {"file": rel, "sha256": doc.sha256, "pages": doc.n_pages, "source_folder": Path(rel).parts[0]}
    ext = parsers.parse(doc)
    if ext is None:
        rec.update(fields={}, alts={}, issues=[{"severity": "error", "field": "insurer", "message": "unknown insurer"}])
        return rec
    f = ext.fields
    f.update({k: v for k, v in derive(f).items() if f.get(k) is None})
    stem = re.sub(r"\s*(insurance|\(\d+\))\s*", "", pdf.stem, flags=re.I).upper().replace(" ", "")
    if REG_RX.match(stem):
        f["registration_no_filename"] = stem
    f.update(normalize(f))
    rec["fields"] = f
    rec["alts"] = dict(ext.alts)
    rec["issues"] = validate(f, ext.alts, rec["source_folder"])
    return rec


def run(root: str) -> list[dict]:
    root = Path(root)
    OUT.mkdir(parents=True, exist_ok=True)
    recs = []
    for pdf in sorted(root.rglob("*.pdf")):
        try:
            rec = extract_file(pdf, root)
        except Exception as ex:  # never let one bad file stop the batch
            rec = {"file": str(pdf.relative_to(root)), "sha256": None, "fields": {}, "alts": {},
                   "issues": [{"severity": "error", "field": "_file", "message": f"crash: {ex!r}"}]}
        recs.append(rec)
        if rec.get("sha256"):
            (OUT / f"{rec['sha256'][:16]}.json").write_text(json.dumps(rec, default=_json_default, indent=1), encoding="utf-8")
    return recs
