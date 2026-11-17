"""IFFCO-Tokio — Commercial Vehicle Certificate of Insurance cum Schedule.

The vehicle table is a dense grid where each value sits under its column header,
so values are read by layout (below the header), never by text order.
"""
import re

from ..common import ident, money, parse_date, percent, reg_no, title
from ..pdfdoc import PdfDoc
from .base import Extraction

NAME = "IFFCO-Tokio"
DATE = r"(\d{2}/\d{2}/\d{4})"


def parse(doc: PdfDoc) -> Extraction:
    e = Extraction(NAME)
    p0 = doc.page(0)
    B = lambda label, **kw: doc.below(label, page=0, **kw)

    e.set("policy_no", ident(doc.find(r"Policy #:\s*\n?\s*([0-9A-Z-]+)", p0)))
    e.alt("policy_no", "tax_invoice", ident(doc.find(r"Tax Invoice No:\s*([0-9A-Z-]+)", p0)))
    e.set("legacy_policy_no", ident(doc.find(r"P400 Policy #\s*([A-Z0-9]+)", p0)))
    e.set("od_start", parse_date(doc.find(r"From:\s*" + DATE, p0)))
    e.set("od_end", parse_date(doc.find(r"To:\s*Midnight On\s*" + DATE, p0)))
    e.set("issue_date", parse_date(doc.find(r"Invoice/Issuance Date:\s*" + DATE, p0)))
    e.set("insured_name", title(doc.find(r"\n\s*([^\n]+)\nPolicy #:", p0)))

    e.set("registration_no", reg_no(B(r"Registration Mark & No\.", max_dy=25)))
    e.set("year_of_manufacture", doc.find(r"(\d{4})", B(r"Year of Manuf\.", max_dy=25) or ""))
    vname = title(B(r"Vehicle Name", max_dy=20))  # e.g. 'GREVOL EVAUM' = make + model in one cell
    e.set("model", vname)
    if vname:
        e.set("make", vname.split()[0])
    e.set("vehicle_class", title(B(r"Make of Vehicle", max_dy=20)))
    e.set("cubic_capacity", B(r"CC", max_dy=25))
    e.set("coverage_printed", title(B(r"Coverage", max_dy=25)))
    e.set("idv", money(B(r"IDV in Rs\.", max_dy=25)))
    e.alt("idv", "total_value", money(B(r"Total Value", max_dy=15)))
    e.set("engine_no", ident(B(r"Engine No\.", max_dy=20)))
    e.set("chassis_no", ident(B(r"Chassis No\.", max_dy=20)))
    e.set("city", title(doc.find(r"Place Of Supply:\s*\n?\s*([A-Z][A-Z ]+?)(?:\s+GSTIN)?\s*$", p0, flags=re.M)))
    e.set("product", "Commercial Vehicle Package Policy")

    # Premiums. 'Net (A)' excludes add-on covers (e.g. depreciation waiver), so OD premium is
    # taken as GST taxable total minus TP (Net (B)); the GST row must satisfy taxable + tax = gross.
    tp = money(doc.find(r"Net \(B\)\s*\n\s*([\d.]+)", p0))
    e.set("tp_premium", tp)
    e.set("od_base_premium", money(doc.find(r"Net \(A\)\s*\n\s*([\d.]+)", p0)))
    e.set("total_premium", money(B(r"Net Premium Rs\.", max_dy=15)))
    m = re.search(r"\nTotal\s*\n((?:\s*[\d.]+\s*\n?){3,5})", p0)
    if m:
        nums = [float(x) for x in m.group(1).split()]
        for k in range(2, len(nums)):  # find gross = taxable + taxes
            if abs(nums[0] + sum(nums[1:k]) - nums[k]) < 0.05:
                e.alt("total_premium", "gst_table", round(nums[k], 2))
                if tp is not None:
                    e.set("od_premium", round(nums[0] - tp, 2))
                break
    e.set("ncb_percent", percent(doc.find(r"No Claim Discount\s*\n?\s*\(\s*([\d.]+)\s*%\)", p0)))

    addons = []
    if re.search(r"DEPRECIATION WAIVER\s*\(UIN", doc.text, re.I) or re.search(r"Depreciation Wave?i?r Cover", doc.text, re.I):
        addons.append("Depreciation Waiver")
    if re.search(r"IMT 23\s*\n\s*[1-9]", p0):
        addons.append("IMT 23 (Lamps, Tyres, Mudguards, Bumpers)")
    e.set("addons", addons)
    # "Under Hire Purchase /Hypothecated/Lease Agreement with <FINANCIER NAME>"
    e.set("hypothecation", title(doc.continued(r"Lease Agreement with\s*", page=0)))
    return e
