"""Normalisers shared by all parsers: dates, money, identifiers."""
from __future__ import annotations

import re
from datetime import date, datetime

EMPTY = {"", "-", "--", "NA", "N/A", "NIL", "NONE", "UNKNOWN", "NULL"}


def clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip(" :\t")
    return None if s.upper() in EMPTY else s


_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%Y-%m-%d", "%d %b %Y", "%d.%m.%Y"]


def parse_date(s: str | None) -> date | None:
    s = clean(s)
    if not s:
        return None
    s = re.sub(r"\s+", " ", s.replace(" ,", ","))
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
            return d if 1990 <= d.year <= 2100 else None
        except ValueError:
            pass
    return None


def money(s: str | None) -> float | None:
    s = clean(s)
    if not s:
        return None
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def ident(s: str | None) -> str | None:
    """Chassis / engine / policy style identifiers: uppercase, no inner whitespace."""
    s = clean(s)
    return re.sub(r"\s+", "", s).upper() if s else None


def reg_no(s: str | None) -> str | None:
    """Registration number: uppercase, strip spaces and dashes (keeps 'NEW' style temp numbers)."""
    s = clean(s)
    if not s:
        return None
    s = s.upper().replace(" ", "").replace("-", "")
    return s


def percent(s: str | None) -> float | None:
    s = clean(s)
    if not s:
        return None
    m = re.search(r"-?\d+(\.\d+)?", s)
    return float(m.group()) if m else None


def title(s: str | None) -> str | None:
    s = clean(s)
    return s.upper() if s else None


# Chassis numbers here are 17-char VIN-style codes. Indian OEMs do use I/O/Q
# (e.g. MA1QXYZ24F1234567), so the strict ISO-3779 alphabet is NOT enforced.
VIN_RX = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9]{17}$")
REG_RX = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}$")
