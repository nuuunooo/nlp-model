"""Scoped, offline checks for explicitly observed market inspection facts."""

import re

from .incidents import incident_spans
from .liquor_consumption import consumption_evidence
from .pilot_evidence import eligible_incident


FOOD_WORK = re.compile(
    r"\b(?:handling|serving|preparing|packing)\b.{0,35}\b(?:cooked food|ready to eat food|unwrapped food)\b"
    r"|\b(?:nagtitinda|nagbebenta)\s+ng\s+(?:kakanin|lutong pagkain)\b"
    r"|\b(?:nag iihaw|nagluluto)\b"
)
MISSING_HAIRNET = re.compile(r"\b(?:no|without|missing|walang(?: suot na)?)\s+(?:a\s+)?hair\s*nets?\b")
VENDING = re.compile(r"\b(?:selling|nagtitinda|nagbebenta)\b")
MISSING_ID = re.compile(
    r"\b(?:no|without|walang)\s+(?:a\s+)?(?:(?:assigned|market|vendor)\s+)?(?:id|identification card)\b"
)
ID_DISPLAY_ONLY = re.compile(
    r"\b(?:walang suot na id|id not displayed|not wearing (?:an? |the )?(?:vendor )?id|"
    r"nasa bulsa|(?:di|hindi)(?:\s+\w+){0,3}\s+mapakita|unable to show)\b"
)
ID_REQUIREMENT = re.compile(
    r"\b(?:required to|must|kailangang|dapat)\b.{0,25}\b(?:wear|display|show|isuot|ipakita)\b"
    r".{0,20}\b(?:id|identification card)\b"
)
UNCERTAIN_ID = re.compile(r"\b(?:daw|raw|reported(?:ly)?|claimed|maybe|baka|ipinakita naman)\b")
PORTER = re.compile(r"\b(?:porter[s]?|kargador)\b")
DOUBLE_RATE = re.compile(
    r"\b(?:ayaw tumanggap|refused to serve|refused the job)\b.{0,95}\b(?:doble|double)\b"
)
EVENT = re.compile(r"\b(?:karaoke|videoke|show|concert|performance)\b")
OBSERVED_EVENT = re.compile(r"\b(?:tuloy|nagpatuloy|continued|ran|played|ended|stopped)\b")
PROSPECTIVE_EVENT = re.compile(r"\b(?:scheduled|planned|will (?:run|continue)|bukas|mamaya|balak|cancelled|canceled)\b")
CLOCK = r"(?P<hour>\d{1,2})(?:\s+([0-5]\d))?\s*(?P<period>am|pm|mn|nn)\b"
ACTUAL_END = re.compile(r"\b(?:hanggang|until|ended at|stopped at)\s+" + CLOCK)
LIMIT_AFTER = re.compile(r"\b" + CLOCK + r"\s+(?:lang|lamang|only)\s+(?:ang\s+)?(?:allowed|permitted|pinapayagan)\b")
LIMIT_BEFORE = re.compile(r"\b(?:allowed until|permitted until|end by|end at|cutoff(?: of)?|hanggang)\s+" + CLOCK)
PERMIT = re.compile(r"\b(?:entertainment permit|event permit|event approval|approved end time)\b")
EQUIPMENT = re.compile(r"\b(?:chiller|freezer|refrigerator|pridyider)\b")
BROKEN = re.compile(r"\b(?:sira|sirang|broken|out of order|not working)\b")
UNREPAIRED = re.compile(r"\b(?:di|hindi)\s+pa(?:\s+rin)?\s+(?:pinapagawa|inaayos|naayos)\b|\bstill unrepaired\b")
WARNING = re.compile(r"\b(?:kahit may warning na|despite (?:a |the )?(?:repair )?(?:warning|notice)|matapos (?:ang )?paalalahanan)\b")
CORRECTED = re.compile(r"\b(?:repaired|fixed|naayos|napagawa)\s+na\b|\b(?:now repaired|now working)\b")
CLEAN_STALL = re.compile(r"\b(?:malinis ang (?:stall|puwesto)|(?:stall|counter) (?:is |was )?clean)\b")
ICED_FISH = re.compile(r"\b(?:may yelo ang isda|fish (?:was |is )?on ice)\b")
NO_PESTS = re.compile(r"\b(?:walang langaw|no flies)\b")
FOOD_HAZARD = re.compile(r"\b(?:marumi|panis|spoiled|contaminated|mabaho|walang yelo)\b")
REPORTED = re.compile(r"\b(?:daw|raw|reportedly|mukhang|alleged)\b")


def clock_value(match):
    hour, minute, period = int(match["hour"]), int(match[2] or 0), match["period"]
    if period in {"mn", "nn"}:
        return {"mn": 0, "nn": 720}[period] if (hour, minute) == (12, 0) else None
    if not 1 <= hour <= 12:
        return None
    return (hour % 12 + (12 if period == "pm" else 0)) * 60 + minute


def event_overran(observed):
    if (not EVENT.search(observed) or not OBSERVED_EVENT.search(observed) or not PERMIT.search(observed)
            or PROSPECTIVE_EVENT.search(observed)):
        return False
    ends = list(ACTUAL_END.finditer(observed))
    if not ends:
        return False
    limit_context = observed[ends[0].end():]
    limits = list(LIMIT_AFTER.finditer(limit_context)) or list(LIMIT_BEFORE.finditer(limit_context))
    if len(limits) != 1 or len(ends) > 2:
        return False
    actual, allowed = clock_value(ends[0]), clock_value(limits[0])
    if actual is None or allowed is None:
        return False
    if actual == 0 and 720 <= allowed < 1440:
        actual = 1440
    return actual > allowed


def assess_market_note(description, normalize, consumption_policy, *, market_inspection):
    findings, reviews = {}, {}
    compliant = set()
    for unit in incident_spans(description, normalize):
        if not eligible_incident(unit):
            continue
        observed = unit.text
        if ID_DISPLAY_ONLY.search(observed):
            if ID_REQUIREMENT.search(unit.context) and not UNCERTAIN_ID.search(observed):
                findings["Vendor Identification"] = "stated_id_display_requirement_breached"
            else:
                reviews["Vendor Identification"] = "verify_display_requirement_and_assigned_id"
        if PORTER.search(observed) and DOUBLE_RATE.search(observed):
            reviews["Porter Regulation"] = "verify_posted_rate_or_service_rule"
        if REPORTED.search(observed):
            continue
        if FOOD_WORK.search(observed) and MISSING_HAIRNET.search(observed):
            findings["DressCode"] = "missing_hairnet_during_food_work"
        if VENDING.search(observed) and MISSING_ID.search(observed) and not ID_DISPLAY_ONLY.search(observed):
            findings["Vendor Identification"] = "missing_id_during_vending"
        if event_overran(observed):
            findings["Entertainment Activities"] = "observed_end_after_permit_cutoff"
        if (EQUIPMENT.search(observed) and BROKEN.search(observed) and UNREPAIRED.search(observed)
                and WARNING.search(observed) and not CORRECTED.search(observed)):
            findings["Stall Management"] = "stall_equipment_unrepaired_after_warning"
        if (CLEAN_STALL.search(observed) and ICED_FISH.search(observed) and NO_PESTS.search(observed)
                and not FOOD_HAZARD.search(observed)):
            compliant.add("Sanitation")
    for route, _ in consumption_evidence(
        description, normalize, consumption_policy, market_inspection=market_inspection,
    ):
        findings.setdefault("Liquor", route)
    return findings, {code: reason for code, reason in reviews.items() if code not in findings}, sorted(compliant - findings.keys())
