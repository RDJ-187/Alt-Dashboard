"""ICICI Lombard — Goods Carrying Vehicles Package Policy.

Page 1 = "Risk Assumption Letter" with a clean label/value table (primary source).
Page 2 = schedule; its vehicle table wraps long values over several lines (chassis
'MBX0000AB1' + 'E123456'), so cells are re-joined by column position (cross-check).
"""
import re

from ..common import ident, money, parse_date, percent, reg_no, title
from ..pdfdoc import PdfDoc
from .base import Extraction

NAME = "ICICI Lombard"
MON = r"([A-Z][a-z]{2} \d{1,2}, \d{4})"


def parse(doc: PdfDoc) -> Extraction:
    e = Extraction(NAME)
    p0 = doc.page(0)
    sched = "\n".join(doc.page_texts[1:])
    L = lambda label: doc.right_of(label, page=0)          # cover-letter table
    S = lambda label: doc.right_of(label, page=1)          # schedule key/value rows
    cell = lambda label: doc.below(label, page=1, max_dy=45, n=4, joiner="")  # schedule grid cell (layout)
    grid = lambda header, j="": doc.grid_value(1, header, j)                   # schedule grid cell (pdfplumber)

    e.set("policy_no", ident(doc.find(r"Policy No\.\s+(\d{4}/\d+/\d+/\d+)", p0)))
    e.alt("policy_no", "schedule", ident(S(r"Policy No\.")))

    period = L(r"Period of Insurance")
    m = re.search(MON + r"\s+to\s+" + MON, period or "")
    if m:
        e.set("od_start", parse_date(m.group(1)))
        e.set("od_end", parse_date(m.group(2)))
    m = re.search(MON + r"\s+[\d:]+\s+to\s+Midnight of\s+" + MON, sched)
    if m:
        e.alt("od_start", "schedule", parse_date(m.group(1)))
        e.alt("od_end", "schedule", parse_date(m.group(2)))
    e.set("issue_date", parse_date(doc.find(r"^\s*" + MON + r"\s*$", sched, flags=re.M)))

    e.set("insured_name", title(L(r"Name of the Insured")))
    e.alt("insured_name", "schedule", title(S(r"Name of the Insured")))
    mm = L(r"Vehicle Make / Model")
    if mm and "/" in mm:
        make, model = mm.split("/", 1)
        e.set("make", title(make))
        e.set("model", title(model))
    e.alt("make", "schedule_grid", title(grid(r"Make", " ")))
    e.set("city", title(L(r"RTO City")))
    e.alt("city", "schedule", title(S(r"RTO Location")))
    e.set("registration_no", reg_no(L(r"Vehicle Registration No\.")))
    e.alt("registration_no", "schedule_grid", reg_no(grid(r"Vehicle Registration No\.")))
    e.set("registration_date", parse_date(L(r"Vehicle Registration Date")))
    e.set("engine_no", ident(L(r"Engine No\.")))
    e.alt("engine_no", "schedule_grid", ident(grid(r"Engine No\.")))
    e.set("chassis_no", ident(L(r"Chassis No\.")))
    e.alt("chassis_no", "schedule_grid", ident(grid(r"Chassis No\.")))
    e.set("ncb_percent", percent(L(r"Current Year NCB\(%\)")))
    e.set("vehicle_usage", title(L(r"Vehicle Usage")))
    e.set("year_of_manufacture", doc.find(r"\b(20\d{2})\b", grid(r"Mfg Yr", " ") or ""))
    e.set("carrier_type", title(S(r"Vehicle Class")))
    e.set("vehicle_class", title(grid(r"Vehicle SubClass", " ")))
    e.set("body_type", title(grid(r"Type of Body", " ")))
    e.set("product", "Goods Carrying Vehicles Package Policy")

    e.set("previous_policy_no", ident(L(r"Previous Policy No\.")))
    e.set("previous_insurer", title(L(r"Previous Insurer Name")))
    e.set("previous_policy_type", title(L(r"Previous Policy Type")))
    pp = L(r"Previous Policy Period")
    m = re.search(r"(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})", pp or "")
    if m:
        e.set("previous_policy_start", parse_date(m.group(1)))
        e.set("previous_policy_end", parse_date(m.group(2)))
    e.set("hypothecation", title(S(r"Hypothecated To")))

    e.set("idv", money(doc.find(r"([\d,]+\.\d{2})\s*\n\s*Premium Details", sched)))
    e.set("od_premium", money(doc.find(r"Total Own Damage Premium\s*\(A\)\s*\n\s*([\d,]+\.\d{2})", sched)))
    e.set("tp_premium", money(doc.find(r"Total Liability Premium\s*\(B\)\s*\n\s*([\d,]+\.\d{2})", sched)))
    e.set("total_premium", money(doc.find(r"Total Premium Payable in\s*\S*\s*\n\s*([\d,]+\.\d{2})", sched)))
    e.alt("total_premium", "receipt", money(doc.right_of(r"Premium Amount \(.\)", page=1)))

    uin = re.search(r"Unique Identification Number \(UIN\) Details\s*\n(.*?)\nIRDAN", sched, re.S)
    if uin:
        e.set("addons", sorted({a.strip() for a in uin.group(1).split("\n") if a.strip()}))
    e.set("compulsory_deductible", money(doc.find(r"Compulsory Deductible:\s*\S*\s*([\d,]+\.\d{2})", sched)))
    return e
