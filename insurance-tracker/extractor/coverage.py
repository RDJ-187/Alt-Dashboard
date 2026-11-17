"""Coverage derivation: policy type, fire cover, chassis-damage cover and causes.

Indian motor policies follow the IRDAI / Indian Motor Tariff wording. Section I
(Own Damage) insures loss of or damage to the vehicle — body and chassis — from a
fixed list of perils. So if Own Damage cover exists, chassis damage is covered for
those perils; fire is one of them unless the policy prints an exclusion.
"""
from __future__ import annotations

OD_PERILS = [
    "Fire, explosion, self-ignition, lightning",
    "Burglary, housebreaking, theft",
    "Riot and strike",
    "Earthquake (fire and shock damage)",
    "Flood, typhoon, hurricane, storm, tempest, inundation, cyclone, hailstorm, frost",
    "Accidental external means (collision, overturning)",
    "Malicious act",
    "Terrorist activity",
    "Transit by road, rail, inland waterway, lift, elevator or air",
    "Landslide, rockslide",
]


def derive(f: dict) -> dict:
    od = (f.get("od_premium") or 0) > 0
    tp = (f.get("tp_premium") or 0) > 0
    out: dict = {}

    if od and tp:
        out["policy_type"] = "Comprehensive (OD + TP)"
    elif od:
        out["policy_type"] = "Stand-alone OD"
    elif tp:
        out["policy_type"] = "Liability Only (TP)"

    # Package policies: TP period = policy period. Stand-alone OD carries its own TP dates.
    if od and tp and not f.get("tp_start"):
        out["tp_start"], out["tp_end"] = f.get("od_start"), f.get("od_end")

    excl = f.get("fire_exclusion_text")
    if od:
        out["fire_covered"] = "Yes - Conditional" if excl else "Yes"
        notes = []
        if excl:
            notes.append("Excluded: " + excl)
        if f.get("fire_total_loss_excess"):
            notes.append(f"Imposed excess on total fire loss: Rs.{f['fire_total_loss_excess']:,.0f}")
        out["fire_note"] = " | ".join(notes) or "Covered under Section I (Own Damage)"
        out["chassis_damage_covered"] = "Yes"
        causes = list(OD_PERILS)
        if excl:
            causes[0] += " (except while charging / at charging station)"
        out["chassis_damage_causes"] = causes
    elif tp:
        out["fire_covered"] = "No"
        out["fire_note"] = "Liability-only policy: no Own Damage cover"
        out["chassis_damage_covered"] = "No"
        out["chassis_damage_causes"] = []
    return out
