"""Field-level validation. A record is only 'verified' when every check passes.

Issue severities:
  error   -> value is missing or provably inconsistent; record goes to review
  warning -> value is as printed on the policy but looks wrong in the real world
             (e.g. engine/chassis swapped by the insurer); shown on the dashboard
"""
from __future__ import annotations

import re
from datetime import date

from .common import REG_RX, VIN_RX

TEXT_FIELDS = {"make", "model", "insured_name", "city"}

REQUIRED = ["insurer", "policy_no", "chassis_no", "engine_no", "od_start", "od_end",
            "insured_name", "total_premium", "idv"]

# folder name fragment -> (min od_end, max od_end) inclusive; folders act as ground-truth labels
FOLDER_WINDOWS = {
    "expired insurance before nov-26": (date(2000, 1, 1), date(2026, 11, 30)),
    "expire due nov and dec-26": (date(2026, 11, 1), date(2026, 12, 31)),
    "insurance 2027": (date(2027, 1, 1), date(2027, 12, 31)),
}


def _norm(v):
    if isinstance(v, str):
        return re.sub(r"[^A-Z0-9]", "", v.upper())
    if isinstance(v, float):
        return round(v, 0)
    return v


def validate(f: dict, alts: dict, source_folder: str) -> list[dict]:
    issues = []
    add = lambda sev, field, msg: issues.append({"severity": sev, "field": field, "message": msg})

    for k in REQUIRED:
        if f.get(k) in (None, ""):
            add("error", k, "missing")

    # in-document cross-checks: every second reading must agree with the primary value
    for k, readings in alts.items():
        for src, v in readings:
            a, b = _norm(v), _norm(f.get(k))
            if f.get(k) is None:
                add("error", k, f"primary missing, {src} has {v!r}")
            elif a == b or (k == "idv" and src == "vehicle_idv_col"):
                continue
            elif k in TEXT_FIELDS and isinstance(a, str) and isinstance(b, str) and (a.startswith(b) or b.startswith(a)) \
                    and min(len(a), len(b)) >= 4:
                continue  # one rendering is truncated/wrapped, not a contradiction
            else:
                add("error", k, f"mismatch: primary {f[k]!r} vs {src} {v!r}")

    ch, en = f.get("chassis_no"), f.get("engine_no")
    if ch and not VIN_RX.match(ch):
        if en and VIN_RX.match(en):
            add("warning", "chassis_no", f"engine/chassis appear SWAPPED on policy (chassis field {ch} is not a VIN; engine field {en} is)")
        else:
            add("warning", "chassis_no", f"non-standard chassis format ({len(ch)} chars)")
    if ch and en and ch == en:
        add("error", "chassis_no", "chassis equals engine number")

    s, e = f.get("od_start"), f.get("od_end")
    if s and e:
        days = (e - s).days
        if days <= 0:
            add("error", "od_end", "end date not after start date")
        elif not 360 <= days <= 366:
            add("warning", "od_end", f"policy term is {days + 1} days (not annual)")
    rn, fn = f.get("registration_no"), f.get("registration_no_filename")
    if rn and not (REG_RX.match(rn) or "NEW" in rn):
        add("warning", "registration_no", f"unusual registration format {rn}")
    if rn and fn and rn != fn and "NEW" not in rn:
        add("warning", "registration_no", f"policy shows {rn} but file is named {fn}")
    if not rn:
        add("warning", "registration_no", "not printed on policy (new vehicle)"
            + (f"; file name suggests {fn}" if fn else ""))

    od, tp, tot = f.get("od_premium"), f.get("tp_premium"), f.get("total_premium")
    if od is not None and tp is not None and tot and od + tp > tot + 1:
        add("error", "total_premium", f"OD {od} + TP {tp} exceeds total {tot}")
    if tot and od is not None and tp is not None and tot > (od + tp) * 1.19 + 2:
        add("error", "total_premium", f"total {tot} exceeds (OD+TP)+18% GST")

    folder = source_folder.lower()
    for key, (lo, hi) in FOLDER_WINDOWS.items():
        if key in folder and e and not lo <= e <= hi:
            add("warning", "od_end", f"expiry {e} outside the '{key}' folder window")
    return issues
