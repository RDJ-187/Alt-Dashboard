"""Stage 2: independent LLM extraction with a local open-source model (Ollama).

The LLM is a *second opinion*, never the sole source:
  * it reads the same layout-filtered text and fills a strict JSON schema
  * every value it returns must be literally present in the PDF text ("grounded"),
    otherwise it is discarded as a hallucination
  * stage 3 (reconcile) compares it field-by-field with the rules result

Results are cached per PDF hash + model + prompt version, so the (slow, CPU-only)
run is resumable and never repeats work.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests

from .pdfdoc import PdfDoc

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat"
MODEL = os.environ.get("INS_LLM_MODEL", "qwen2.5:7b-instruct")
PROMPT_VERSION = "v2"
OUT = Path("data/extracted/llm")
MAX_CHARS = 7000  # ~2k tokens: keeps CPU latency bounded

# Every value is requested EXACTLY AS PRINTED; all parsing (dates, money) happens in code.
# (v1 asked for DD/MM/YYYY and the model converted 'Dec 11, 2026' into US-style 12/11/2026.)
FIELDS = {
    "insurer_name": "Insurance company that issued this policy",
    "policy_number": "Number printed against 'Policy No.' / 'Policy #' / 'Certificate of Insurance and Policy No.' (not UIN, not invoice, not previous policy)",
    "registration_number": "Vehicle registration number; null if not printed",
    "chassis_number": "Value printed against 'Chassis No.' / 'Chassis Number'",
    "engine_number": "Value printed against 'Engine No.' / 'Engine Number' / 'Motor No.'",
    "make": "Vehicle make / manufacturer name",
    "model": "Vehicle model description",
    "insured_name": "Name of the insured",
    "period_start": "Start date of the own-damage policy period, copied as printed",
    "period_end": "End / expiry date of the own-damage policy period, copied as printed",
    "total_idv": "Total IDV amount, copied as printed",
    "total_premium_payable": "Final total premium payable including tax, copied as printed",
    "ncb_percent": "Current no claim bonus / discount percent, copied as printed",
    "hypothecated_to": "Financier / hypothecation / lease company; null if none",
}

SCHEMA = {
    "type": "object",
    "properties": {k: {"type": ["string", "null"]} for k in FIELDS},
    "required": list(FIELDS),
}

SYSTEM = (
    "You extract fields from Indian motor insurance policy documents. The document is given as "
    "visual rows; cells in a row are separated by ' | ', and a table's values sit in the row below "
    "its header row, in the same column order. Copy every value exactly as printed, character for "
    "character. Never guess, never compute, never convert dates or numbers. "
    "If a field is not clearly printed, return null. Output only JSON."
)

_BOILER = re.compile(r"(?i)terms|condition|hereby|provided that|subject to|in case|please|www\.|e-mail|helpline|toll free|declare")


def _doc_text(doc: PdfDoc) -> str:
    """Schedule pages as visual rows, legal boilerplate removed, capped in size."""
    keep = []
    for p in range(min(doc.n_pages, 3)):
        rows = [r for r in doc.row_text(p).split("\n") if len(r) < 160 and not _BOILER.search(r)]
        keep.append("\n".join(rows))
    return "\n=== PAGE ===\n".join(keep)[:MAX_CHARS]


def _prompt(text: str) -> str:
    spec = "\n".join(f"- {k}: {v}" for k, v in FIELDS.items())
    return f"Fields to extract:\n{spec}\n\nDocument text:\n\"\"\"\n{text}\n\"\"\""


def grounded(value: str | None, text: str) -> bool:
    """True if the value (ignoring spaces/punctuation/case) appears in the document text."""
    if value is None:
        return True
    v = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    if not v:
        return True
    return v in re.sub(r"[^A-Z0-9]", "", text.upper())


def extract(doc: PdfDoc, timeout: int = 900) -> dict:
    cache = OUT / MODEL.replace(":", "_") / f"{doc.sha256[:16]}.json"
    if cache.exists():
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("model") == MODEL and c.get("prompt_version") == PROMPT_VERSION:
            return c
    text = _doc_text(doc)
    t0 = time.time()
    r = requests.post(OLLAMA, timeout=timeout, json={
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(text)}],
        "format": SCHEMA,
        "stream": False,
        "options": {"temperature": 0, "seed": 7, "num_ctx": 8192},
    })
    r.raise_for_status()
    body = r.json()
    values = json.loads(body["message"]["content"])
    full = doc.text
    result = {
        "file": str(doc.path), "sha256": doc.sha256, "model": MODEL, "prompt_version": PROMPT_VERSION,
        "seconds": round(time.time() - t0, 1),
        "prompt_tokens": body.get("prompt_eval_count"), "output_tokens": body.get("eval_count"),
        "values": values,
        "ungrounded": [k for k, v in values.items() if not grounded(v, full)],
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result
