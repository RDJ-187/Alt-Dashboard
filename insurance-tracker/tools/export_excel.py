"""Export the DB to Excel in the layout of the client's sample sheet, plus assignment columns.

  python tools/export_excel.py [--out data/Insurance_Tracker.xlsx] [--today 2026-11-16]
"""
import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extractor.db import DB_PATH  # noqa: E402

BUCKETS = [(0, "Expired"), (7, "Critical (0-7 days)"), (30, "Due in 30 days"), (60, "Upcoming (31-60 days)")]


def bucket(days):
    if days is None:
        return "Unknown"
    if days < 0:
        return "Expired"
    for lim, name in BUCKETS[1:]:
        if days <= lim:
            return name
    return "Active"


# (group, header, getter)
COLS = [
    ("Vehicle", "VEHICLE TYPE", lambda r: r["vehicle_class"]),
    ("Vehicle", "OEM", lambda r: r["oem"]),
    ("Vehicle", "Model", lambda r: r["model"]),
    ("Vehicle", "CHASSIS NO", lambda r: r["chassis_no"]),
    ("Vehicle", "Motor No", lambda r: r["engine_no"]),
    ("Vehicle", "Registration No", lambda r: r["registration_no"] or (f"(pending) {r['registration_no_filename']}" if r["registration_no_filename"] else "(pending)")),
    ("Vehicle", "Customer Registered Name", lambda r: r["insured_name"]),
    ("Vehicle", "Insurance Co", lambda r: r["insurer"]),
    ("Vehicle", "City", lambda r: r["city_clean"]),
    ("Vehicle", "Insured Name", lambda r: r["insured_name"]),
    ("Current Policy", "Policy Number", lambda r: r["policy_no"]),
    ("Current Policy", "OD Start date", lambda r: _d(r["od_start"])),
    ("Current Policy", "OD End date", lambda r: _d(r["od_end"])),
    ("Current Policy", "TPC Start date", lambda r: _d(r["tp_start"])),
    ("Current Policy", "TPC End date", lambda r: _d(r["tp_end"])),
    ("Current Policy", "Amount", lambda r: _n(r["total_premium"])),
    ("Previous Policy", "Policy Number", lambda r: r["previous_policy_no"]),
    ("Previous Policy", "OD Start date", lambda r: _d(r["previous_policy_start"])),
    ("Previous Policy", "OD End date", lambda r: _d(r["previous_policy_end"])),
    ("Previous Policy", "Insurer", lambda r: r["previous_insurer"]),
    ("Finance", "Hypothecation", lambda r: r["financier"]),
    ("Own Damage Cover", "Policy Type", lambda r: r["policy_type"]),
    ("Own Damage Cover", "IDV (Rs)", lambda r: _n(r["idv"])),
    ("Own Damage Cover", "OD Premium (Rs)", lambda r: _n(r["od_premium"])),
    ("Own Damage Cover", "Fire Covered", lambda r: r["fire_covered"]),
    ("Own Damage Cover", "Fire Note", lambda r: r["fire_note"]),
    ("Own Damage Cover", "Chassis Damage Covered", lambda r: r["chassis_damage_covered"]),
    ("Own Damage Cover", "Covered Causes", lambda r: "; ".join(json.loads(r["chassis_damage_causes"] or "[]"))),
    ("Own Damage Cover", "Add-on Covers", lambda r: ", ".join(json.loads(r["addons"] or "[]"))),
    ("Tracker", "Days to Expiry", lambda r: r["_days"]),
    ("Tracker", "Expiry Status", lambda r: bucket(r["_days"])),
    ("Tracker", "Data Status", lambda r: r["status"]),
    ("Tracker", "Source File", lambda r: r["file"]),
]


def _d(s):
    return date.fromisoformat(s) if s else None


def _n(s):
    return float(s) if s not in (None, "") else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/Insurance_Tracker.xlsx")
    ap.add_argument("--today", default=date.today().isoformat())
    a = ap.parse_args()
    today = date.fromisoformat(a.today)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM vehicles ORDER BY od_end")]
    for r in rows:
        r["_days"] = (date.fromisoformat(r["od_end"]) - today).days if r["od_end"] else None

    wb = Workbook()
    ws = wb.active
    ws.title = "Insurance Tracker"
    thin = Side(style="thin", color="D0D5DD")
    head_fill = PatternFill("solid", fgColor="1F2A44")
    group_fill = PatternFill("solid", fgColor="E8ECF4")

    # group header row (merged), then column header row — mirrors the sample sheet's two-row header
    c = 1
    while c <= len(COLS):
        g = COLS[c - 1][0]
        end = c
        while end < len(COLS) and COLS[end][0] == g:
            end += 1
        ws.cell(1, c, g).font = Font(bold=True, color="1F2A44")
        ws.cell(1, c).fill = group_fill
        ws.cell(1, c).alignment = Alignment(horizontal="center")
        if end > c:
            ws.merge_cells(start_row=1, start_column=c, end_row=1, end_column=end)
        c = end + 1
    for j, (_, h, _) in enumerate(COLS, 1):
        cell = ws.cell(2, j, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = Border(bottom=thin)
    for i, r in enumerate(rows, 3):
        for j, (_, h, get) in enumerate(COLS, 1):
            v = get(r)
            cell = ws.cell(i, j, v)
            if isinstance(v, date):
                cell.number_format = "DD-MMM-YYYY"
            elif isinstance(v, float):
                cell.number_format = "#,##0"
    widths = {"CHASSIS NO": 21, "Motor No": 19, "Covered Causes": 60, "Fire Note": 45, "Source File": 50,
              "Customer Registered Name": 30, "Insured Name": 30, "Model": 26, "Add-on Covers": 34}
    for j, (_, h, _) in enumerate(COLS, 1):
        ws.column_dimensions[get_column_letter(j)].width = widths.get(h, 15)
    ws.freeze_panes = "E3"
    ws.auto_filter.ref = f"A2:{get_column_letter(len(COLS))}{len(rows) + 2}"

    status_col = get_column_letter([h for _, h, _ in COLS].index("Expiry Status") + 1)
    rng = f"A3:{get_column_letter(len(COLS))}{len(rows) + 2}"
    for text, color in [("Expired", "FDE2E1"), ("Critical", "FDE2E1"), ("Due in 30", "FEF0C7"), ("Upcoming", "FEF9C3")]:
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("{text}",${status_col}3))'],
                                                       fill=PatternFill("solid", fgColor=color)))

    # data-quality sheet
    dq = wb.create_sheet("Data Quality")
    dq.append(["Source File", "Chassis No", "Severity", "Field", "Message"])
    for row in con.execute("""SELECT p.file, p.chassis_no, i.severity, i.field, i.message
                              FROM issues i JOIN policies p ON p.id=i.policy_id ORDER BY i.severity, i.field"""):
        dq.append(list(row))
    for row in con.execute("SELECT file, '', 'info', 'duplicate', 'identical copy of ' || duplicate_of FROM duplicates"):
        dq.append(list(row))
    for j, w in enumerate([60, 22, 10, 18, 90], 1):
        dq.column_dimensions[get_column_letter(j)].width = w
    for cell in dq[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    wb.save(a.out)
    from collections import Counter
    print(f"Wrote {a.out}: {len(rows)} vehicles  |  " + ", ".join(f"{k}: {v}" for k, v in Counter(bucket(r['_days']) for r in rows).most_common()))


if __name__ == "__main__":
    main()
