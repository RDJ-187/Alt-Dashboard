"""Stage 3: compare rules vs LLM field-by-field and decide a record status.

Per-field verdicts
  agree        rules and LLM independently produced the same value
  rules_only   LLM returned null or an ungrounded (hallucinated) value -> rules value kept
  llm_only     rules found nothing, LLM found a grounded value -> NOT auto-accepted, review
  conflict     both produced different values -> review
Record status
  verified     no validation errors and no conflict / llm_only on any critical field
  review       anything else (the dashboard review queue)
"""
from __future__ import annotations

import re

from .common import money, parse_date

# rules field -> (llm key, comparison kind)
MAP = {
    "insurer": ("insurer_name", "contains"),
    "policy_no": ("policy_number", "id"),
    "registration_no": ("registration_number", "id"),
    "chassis_no": ("chassis_number", "id"),
    "engine_no": ("engine_number", "id"),
    "make": ("make", "contains"),
    "model": ("model", "contains"),
    "insured_name": ("insured_name", "text"),
    "od_start": ("period_start", "date"),
    "od_end": ("period_end", "date"),
    "idv": ("total_idv", "money"),
    "total_premium": ("total_premium_payable", "money"),
    "ncb_percent": ("ncb_percent", "money"),
    "hypothecation": ("hypothecated_to", "text"),
}
CRITICAL = {"policy_no", "chassis_no", "engine_no", "registration_no", "od_start", "od_end", "total_premium", "idv"}
# non-critical fields where the LLM finds a grounded value the rules missed -> review (rules gap)
GAP_WATCH = {"hypothecation", "insured_name"}

_alnum = lambda v: re.sub(r"[^A-Z0-9]", "", str(v).upper())


_DATE_RXS = [r"\d{1,2}/\d{1,2}/\d{4}", r"\d{1,2}-\d{1,2}-\d{4}", r"\d{1,2}-[A-Za-z]{3}-\d{4}",
             r"[A-Za-z]{3,9} \d{1,2}, \d{4}", r"\d{4}-\d{2}-\d{2}"]


def _llm_date(s):
    """Parse a date the LLM copied as printed (may carry times / words around it). Indian D/M/Y order."""
    if s is None:
        return None
    for rx in _DATE_RXS:
        m = re.search(rx, str(s))
        if m:
            d = parse_date(m.group())
            if d:
                return d
    return None


def unusable(kind: str, l) -> bool:
    """LLM answer that cannot be compared (e.g. two amounts in one money field)."""
    if kind == "money":
        return len(re.findall(r"\d[\d,]*(?:\.\d+)?", str(l))) != 1
    if kind == "date":
        return _llm_date(l) is None
    return False


def same(kind: str, r, l) -> bool:
    if kind == "id":
        # a cell may print extra data after a separator: 'D123456789 / 01012025' (policy no / issue date)
        # LLM sometimes copies the neighbouring cell too: '1-6ABCDEFG | P400 Policy # N1234567'
        first = re.split(r"\s+(?:/|\|)\s+|\s+(?=P400\b)", str(l).strip())[0]
        return _alnum(r) == _alnum(l) or _alnum(r) == _alnum(first)
    if kind == "date":
        return str(r) == str(_llm_date(l))
    if kind == "money":
        a, b = money(str(r)), money(str(l))
        return a is not None and b is not None and abs(a - b) <= 1
    a, b = _alnum(r), _alnum(l)
    if kind == "contains":
        return a in b or b in a
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def reconcile(rec: dict, llm: dict | None) -> dict:
    f = rec["fields"]
    checks = []
    for field, (key, kind) in MAP.items():
        rv = f.get(field)
        if llm is None:
            checks.append({"field": field, "rules": rv, "llm": None, "verdict": "rules_only"})
            continue
        lv = llm["values"].get(key)
        lv_used = None if key in llm.get("ungrounded", []) else lv  # hallucinated values are discarded
        if lv_used not in (None, "") and unusable(kind, lv_used):
            verdict = "llm_unusable"  # malformed LLM answer: no evidence either way
        elif rv in (None, "") and lv_used in (None, ""):
            verdict = "both_empty"
        elif lv_used in (None, ""):
            verdict = "rules_only"
        elif rv in (None, ""):
            verdict = "llm_only"
        else:
            verdict = "agree" if same(kind, rv, lv_used) else "conflict"
        checks.append({"field": field, "rules": rv, "llm": lv, "verdict": verdict,
                       "llm_ungrounded": key in llm.get("ungrounded", [])})

    errors = [i for i in rec["issues"] if i["severity"] == "error"]
    bad = [c for c in checks if (c["field"] in CRITICAL and c["verdict"] in ("conflict", "llm_only"))
           or (c["field"] in GAP_WATCH and c["verdict"] == "llm_only")]
    agree = sum(c["verdict"] == "agree" for c in checks)
    compared = sum(c["verdict"] in ("agree", "conflict") for c in checks)
    return {
        "checks": checks,
        "status": "verified" if not errors and not bad else "review",
        "review_reasons": [f"{i['field']}: {i['message']}" for i in errors]
                          + [f"{c['field']}: rules={c['rules']!r} llm={c['llm']!r} ({c['verdict']})" for c in bad],
        "llm_agreement": round(agree / compared, 3) if compared else None,
    }
