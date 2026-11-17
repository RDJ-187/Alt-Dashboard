"""Go Digit — Two-Wheeler Stand-alone Own Damage policy.

Labels and values are scrambled in reading order and a rotated watermark overlays
the tables, so values are read by layout (right of label). The page footer line
'<REG> <MAKE MODEL> <OD start> <OD end> Digit ...' and the file name (= chassis no.)
give independent cross-checks. TP cover is a separate policy from another insurer.
"""
import re

from ..common import ident, money, parse_date, percent, reg_no, title
from ..pdfdoc import PdfDoc
from .base import Extraction

NAME = "Go Digit"


def parse(doc: PdfDoc) -> Extraction:
    e = Extraction(NAME)
    p0, p1 = doc.page(0), doc.page(1)
    R = lambda label: doc.right_of(label, page=0)

    pol = R(r"Policy No\.")
    if pol:
        e.set("policy_no", ident(pol.split("/")[0]))
    e.set("issue_date", parse_date(R(r"Policy Issue Date")))
    e.set("od_start", parse_date(R(r"From")))
    e.set("od_end", parse_date(R(r"To")))
    foot = re.search(r"^([A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}) (.+?) (\d{4}-\d{2}-\d{2}) (\d{4}-\d{2}-\d{2}) Digit (.+)$", doc.text, re.M)
    if foot:
        e.alt("registration_no", "footer", reg_no(foot.group(1)))
        e.alt("od_start", "footer", parse_date(foot.group(3)))
        e.alt("od_end", "footer", parse_date(foot.group(4)))
        e.set("product", foot.group(5).strip())

    e.set("insured_name", title(R(r"Name")))
    e.set("registration_no", reg_no(R(r"Vehicle Registration No\.")))
    e.set("city", title(R(r"RTO Location")))
    e.set("make", title(R(r"Make")))
    e.set("model", title(R(r"Model/Vehicle Variant \(Sub-")))
    e.set("fuel_type", title(R(r"Fuel Type")))
    yr = R(r"Year of Regn/Year of Mfg\.") or ""
    m = re.match(r"(\d{4})/(\d{4})", yr)
    if m:
        e.set("registration_year", m.group(1))
        if m.group(2) != "0001":
            e.set("year_of_manufacture", m.group(2))
    e.set("engine_no", ident(R(r"Engine No\.")))
    e.set("chassis_no", ident(R(r"Chassis No\.")))
    e.alt("chassis_no", "file_name", ident(doc.path.stem) if re.fullmatch(r"M[A-Z0-9]{16}", doc.path.stem) else None)
    e.set("idv", money(R(r"Total IDV.*")))
    e.set("ncb_percent", percent(R(r"NCB % \(Current Policy\)")))
    e.set("hypothecation", title(R(r"Financier Details")))
    e.set("vehicle_class", "TWO WHEELER")

    m = re.search(r"Gross Premium\s*\n\s*\S+\s*\n\s*\d{4}-\d{2}-\d{2}\s*\n\s*([\d.]+)\s*\n\s*[\d.]+(?:\s*\n\s*[\d.]+){4}\s*\n\s*([\d.]+)", p1)
    if m:
        e.set("od_premium", money(m.group(1)))     # stand-alone OD: whole net premium is OD
        e.set("total_premium", money(m.group(2)))
    e.set("tp_premium", 0.0)

    m = re.search(r"\n([A-Z0-9]{10,})\n(.+?)\nTo\nFrom\nPeriod of Policy for Third Party Liability Cover", p1)
    if m:
        e.set("tp_policy_no", ident(m.group(1)))
        e.set("tp_insurer", title(m.group(2)))
    m = re.search(r"THIRD PARTY LIABILITY DETAILS\s*\n\s*(\d{2}-[A-Za-z]{3}-\d{4})\s*\n\s*(\d{2}-[A-Za-z]{3}-\d{4})", p1)
    if m:
        e.set("tp_start", parse_date(m.group(1)))
        e.set("tp_end", parse_date(m.group(2)))
    m = re.search(r"Optional Coverage Details\s*\n(.+)", p0)
    e.set("addons", [m.group(1).strip()] if m else [])

    excl = re.search(r"(Any loss or damage to the Insured Vehicle resulting from Fire.*?excluded from the scope of cover)", doc.text, re.S | re.I)
    if excl:
        e.set("fire_exclusion_text", re.sub(r"\s+", " ", excl.group(1)))
    return e
