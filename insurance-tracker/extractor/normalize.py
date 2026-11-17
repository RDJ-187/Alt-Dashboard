"""Canonical names for grouping on the dashboard. Raw printed values are never overwritten:
each canonical value lives in its own column (oem, financier, city_clean, state).

Alias tables are plain data — extend them when a new spelling shows up in the
'unmapped' list printed by tools/report_rules.py.
"""
from __future__ import annotations

import re

OEM_ALIASES = [  # (regex on make or model, canonical OEM)
    (r"EULER", "Euler Motors"),
    (r"ALTIGREEN", "Altigreen"),
    (r"GREEN EVOLVE|GREVOL|EVAUM", "Green Evolve"),
    (r"OMEGA", "Omega Seiki Mobility"),
    (r"BAJAJ", "Bajaj Auto"),
    (r"PIAGGIO", "Piaggio"),
    (r"KINETIC", "Kinetic Green"),
    (r"QUANTUM", "Quantum Energy"),
    (r"\bTVS\b", "TVS Motor"),
    (r"MAHINDRA", "Mahindra"),
    (r"ATUL", "Atul Auto"),
]

FINANCIER_ALIASES = [
    (r"AMU\s*LEASING", "AMU Leasing Pvt Ltd"),
    (r"BLACKSOIL", "BlackSoil Capital Pvt Ltd"),
    (r"TATA\s*CAPITAL", "Tata Capital Ltd"),
    (r"IREDA", "IREDA Ltd"),
    (r"BANSAL\s*CREDITS", "Bansal Credits Ltd"),
    (r"LOANX|ALDER", "LoanX Alder"),
]

CITY_ALIASES = [  # (regex on printed city / RTO, city, state)
    (r"NAVI\s*MUMBAI", "Navi Mumbai", "Maharashtra"),
    (r"MUMBAI", "Mumbai", "Maharashtra"),
    (r"PUNE", "Pune", "Maharashtra"),
    (r"NEW\s*DELHI|^DELHI|DL\d", "Delhi", "Delhi"),
    (r"BENGALURU|BANGALORE", "Bengaluru", "Karnataka"),
    (r"HYDERABAD", "Hyderabad", "Telangana"),
    (r"CHENNAI", "Chennai", "Tamil Nadu"),
    (r"JAIPUR", "Jaipur", "Rajasthan"),
    (r"NOIDA|GAUTAM", "Noida", "Uttar Pradesh"),
    (r"GURGAON|GURUGRAM", "Gurugram", "Haryana"),
    (r"MUZAFFARPUR", "Muzaffarpur", "Bihar"),
    (r"PATNA", "Patna", "Bihar"),
    (r"KOLKATA", "Kolkata", "West Bengal"),
    (r"AHMEDABAD", "Ahmedabad", "Gujarat"),
    (r"LUCKNOW", "Lucknow", "Uttar Pradesh"),
]

STATE_CODES = {
    "DL": "Delhi", "KA": "Karnataka", "MH": "Maharashtra", "TN": "Tamil Nadu", "TS": "Telangana",
    "TG": "Telangana", "UP": "Uttar Pradesh", "BR": "Bihar", "HR": "Haryana", "RJ": "Rajasthan",
    "GJ": "Gujarat", "WB": "West Bengal", "AP": "Andhra Pradesh", "KL": "Kerala", "PB": "Punjab",
}


def _match(table, *texts):
    for rx, *canon in table:
        for t in texts:
            if t and re.search(rx, t, re.I):
                return canon
    return None


def normalize(f: dict) -> dict:
    out = {}
    oem = _match(OEM_ALIASES, f.get("make"), f.get("model"))
    out["oem"] = oem[0] if oem else (f.get("make") or "").title() or None
    fin = _match(FINANCIER_ALIASES, f.get("hypothecation"))
    out["financier"] = fin[0] if fin else (f.get("hypothecation") or "").title() or None
    city = _match(CITY_ALIASES, f.get("city"))
    reg = f.get("registration_no") or ""
    if city:
        out["city_clean"], out["state"] = city
    else:
        out["city_clean"] = (f.get("city") or "").title() or None
        out["state"] = STATE_CODES.get(reg[:2])
    if not out.get("state"):
        out["state"] = STATE_CODES.get(reg[:2])
    return out
