"""Royal Sundaram — Goods Carrying Vehicle Package Policy.

Page 1 = cover letter (clean "Label: value"), page 2 = schedule, page 3 = premium
breakup, last page = GST invoice. Most identifiers are printed on 2+ pages, which
gives us in-document cross-checks.
"""
import re

from ..common import ident, money, parse_date, percent, reg_no, title
from ..pdfdoc import PdfDoc
from .base import Extraction

NAME = "Royal Sundaram"
DATE = r"(\d{2}/\d{2}/\d{4})"
AMT = r"(-?[\d,]+\.\d{2})"


def parse(doc: PdfDoc) -> Extraction:
    e = Extraction(NAME)
    si = doc.page_with("CERTIFICATE OF INSURANCE & POLICY SCHEDULE\n", default=1)  # cover letter may span 2 pages
    p0, p1 = doc.page(0), doc.page(si)
    rest = "\n".join(doc.page_texts[si:])

    # --- policy identity & period
    e.set("policy_no", ident(doc.find(r"Certificate of Insurance and Policy No\.\s*\n\s*([A-Z0-9]+)", p0)))
    e.alt("policy_no", "schedule", ident(doc.find(r"Certificate of Insurance and Policy No\.\s*\n\s*([A-Z0-9]+)", p1)))
    e.alt("policy_no", "invoice", ident(doc.find(r"Policy Number\s*:\s*([A-Z0-9]+)")))

    per = r"From\s+[\d:]+\s+hours on\s+" + DATE + r"\s+To\s+Midnight of\s+" + DATE
    m0, m1 = re.search(per, p0), re.search(per, p1)
    if m0:
        e.set("od_start", parse_date(m0.group(1)))
        e.set("od_end", parse_date(m0.group(2)))
    if m1:
        e.alt("od_start", "schedule", parse_date(m1.group(1)))
        e.alt("od_end", "schedule", parse_date(m1.group(2)))
    e.set("next_renewal_date", parse_date(doc.find(r"NEXT RENEWAL\s*\n?\s*IS ON\s*\n?\s*" + DATE, p0)))
    e.alt("od_end", "next_renewal_box", e.get("next_renewal_date"))  # RS prints renewal date = expiry date
    e.set("issue_date", parse_date(doc.find(r"Invoice Date\s*:\s*" + DATE)))

    # --- insured & vehicle (cover letter primary, schedule as cross-check)
    e.set("insured_name", title(doc.find(r"Name of the Insured:\s*(.+)", p0)))
    e.set("make", title(doc.find(r"Make of the Vehicle:\s*(.+)", p0)))
    e.set("model", title(doc.find(r"Model Description:\s*(.+)", p0)))
    e.alt("model", "schedule", title(doc.find(r"Model Description\s*\n\s*(.+)", p1)))
    e.set("engine_no", ident(doc.find(r"Engine No\.:\s*([A-Z0-9]+)", p0)))
    e.alt("engine_no", "schedule", ident(doc.find(r"Engine Number\s*\n\s*([A-Z0-9]+)", p1)))
    e.set("chassis_no", ident(doc.find(r"Chassis No\.:\s*([A-Z0-9]+)", p0)))
    e.alt("chassis_no", "schedule", ident(doc.find(r"Chassis Number\s*\n\s*([A-Z0-9]+)", p1)))
    # value must contain a digit; new vehicles have an empty cell (next line is the next label)
    e.set("registration_no", reg_no(doc.find(r"Registration Number\s*\n\s*([A-Z0-9/ -]*\d[A-Z0-9/ -]*?)\s*\n", p1)))
    e.set("year_of_manufacture", doc.find(r"Year of Manufacture\s*\n\s*(\d{4})", p1))
    e.set("fuel_type", title(doc.find(r"Fuel Type\s*\n\s*([A-Za-z /]+)", p1)))
    e.set("body_type", title(doc.find(r"Type of Body\s*\n\s*(.+)", p1)))
    e.set("carrier_type", title(doc.find(r"Public Carrier/Private Carrier\s*\n\s*(.+)", p1)))
    e.set("city", title(doc.below(r"Authority", page=si)))
    e.set("vehicle_class", "GOODS CARRYING VEHICLE")
    e.set("product", "Goods Carrying Vehicle Package Policy")

    # --- values & premium
    # columns: vehicle, trailers, non-elec acc, elec acc, CNG kit, TOTAL IDV [, invoice price (newer template)]
    m = re.search(r"Total\s*\n?\s*IDV\s*\n(?:Invoice\s*\nPrice\s*\nValue\s*\n)?((?:\s*[\d,]+\s*\n){6})", p1)
    if m:
        nums = m.group(1).split()
        e.set("idv", money(nums[5]))
        e.alt("idv", "vehicle_idv_col", money(nums[0]))
    e.set("od_premium", money(doc.find(r"TOTAL OWN DAMAGE PREMIUM \(A\)\s*\n\s*" + AMT, rest)))
    e.set("tp_premium", money(doc.find(r"TOTAL LIABILITY PREMIUM \(B\)\s*\n\s*" + AMT, rest)))
    e.set("total_premium", money(doc.find(r"Premium Amount \(Rs\.\)\s*" + AMT, p0)))
    e.alt("total_premium", "premium_schedule", money(doc.find(r"TOTAL PREMIUM PAYABLE\s*\n\s*" + AMT, rest)))
    e.set("ncb_percent", percent(doc.find(r"your policy\s*\((\d+\s*)%\)", p0)))

    # --- history & finance
    e.set("previous_policy_no", ident(doc.find(r"Previous Policy No\.\s*\n\s*([A-Z]*\d[A-Z0-9]*)\s*\n", p0)))
    e.set("previous_insurer", title(doc.find(r"Previous Policy Insurance Co\.\s*\n?\s*(.+)", p0)))
    hyp = doc.continued(r"Hypothecated with\s*")  # follows names wrapped onto the next line
    if hyp and not re.match(r"Nominee", hyp, re.I):
        e.set("hypothecation", title(hyp))

    # --- add-ons with a non-zero premium in "Additional Cover for Package Policies"
    sec = re.search(r"Additional Cover for Package Policies(.*?)TOTAL OWN DAMAGE PREMIUM", rest, re.S)
    if sec:
        addons = []
        for am in re.finditer(r"\d+\.\s*([A-Z][A-Za-z &/-]+?)\s*(?:\(|\n)(.*?)(?=\n\d+\.\s*[A-Z]|\Z)", sec.group(1), re.S):
            amounts = [money(a) for a in re.findall(r"(?<![\w.])(\d[\d,]*\.\d{2})(?!\d)", am.group(2))]
            if amounts and max(amounts) > 0 and "IGST" not in am.group(1):
                addons.append(am.group(1).strip())
        e.set("addons", sorted(set(addons)))

    # --- deductibles / fire excess (feeds coverage logic)
    e.set("compulsory_deductible", money(doc.find(r"Compulsory Deductible \[Rs\.([\d,]+)\]", rest)))
    e.set("fire_total_loss_excess", money(doc.find(r"Imposed Excess for Total Fire Loss \[Rs\.([\d,]+)\]", rest)))
    return e
