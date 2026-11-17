"""Insurer detection and parser dispatch. Adding a new insurer = one new module + one line here."""
from __future__ import annotations

from ..pdfdoc import PdfDoc
from . import go_digit, icici_lombard, iffco_tokio, royal_sundaram
from .base import Extraction

# fingerprint (lowercase, must appear in text) -> parser module
PARSERS = [
    (("royal sundaram general insurance", "irdai reg. no.102"), royal_sundaram),
    (("icici lombard general insurance",), icici_lombard),
    (("iffco-tokio general insurance", "iffco tokio gen"), iffco_tokio),
    (("go digit general insurance",), go_digit),
]


def detect(doc: PdfDoc):
    low = doc.text.lower()
    scores = [(sum(low.count(k) for k in keys), mod) for keys, mod in PARSERS]
    best, mod = max(scores, key=lambda s: s[0])
    return mod if best else None


def parse(doc: PdfDoc) -> Extraction | None:
    mod = detect(doc)
    return mod.parse(doc) if mod else None
