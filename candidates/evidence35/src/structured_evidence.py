"""Interpret facts with explicit roles before the learned evidence decision."""

from datetime import date
from decimal import Decimal
import re

from .description_evidence import QUANTITY, UNIT_DIMENSIONS, UNITS, UNRESOLVED, described_weight_outcome
from .reweigh import description_evidence_issue


WEIGHT_REFERENCE = re.compile(r"\s+(?:(?:calibrated|certified)\s+)?(?:test|check|reference)\s+(?:weight|mass)\b")
SCALE = re.compile(r"\b(?:scale|timbangan)\b")
READING_BEFORE = re.compile(r"\b(?:read|reads|reading|displayed|showed|lumabas)\s*$")
READING_AFTER = re.compile(r"^\s+(?:(?:lang|only)\s+)?(?:ang (?:lumalabas|lumabas)|was (?:displayed|shown))\b")
EXPIRY = re.compile(r"\b(?:expir(?:es|ed|y)(?: date)?|valid until)\s*(?:on )?(\d{4} \d{2} \d{2})\b")
INSPECTION = re.compile(r"\b(?:inspection date|inspected on|inspection on|sinuri noong)\s+(\d{4} \d{2} \d{2})\b")
EXPLICIT_EXPIRY = re.compile(r"\b(?:expired|paso)\b")
EXPIRY_QUALIFIER = re.compile(r"\b(?:no|not|never|without|hindi|di|walang)\s+(?:\w+\s+){0,4}$")
PROSPECTIVE_EXPIRY = re.compile(r"\b(?:if|kung|before|bago|will|soon|about to|malapit nang)\s+(?:\w+\s+){0,4}$")
EXPIRY_OBJECTS = {
    "Permit & Licensing": re.compile(r"\b(?:permit|business license|lisensya|health certificate)\b"),
    "Sanitation": re.compile(r"\b(?:food|fish|canned goods|de lata|pagkain|isda)\b"),
}
SALE = re.compile(r"\b(?:for sale|offered for sale|selling|sold|ibinebenta|binibenta|binebenta)\b")
WITHDRAWN = re.compile(r"\b(?:removed from sale|not for sale|for disposal|inalis sa bentahan)\b")
PERMIT_USE = re.compile(r"\b(?:selling|trading|operat\w+|nagbebenta|nagtitinda)\b")
NEGATED_USE = re.compile(r"\b(?:not|never|hindi|di)\s+(?:actively\s+)?(?:selling|sold|trading|operat\w+|nagbebenta|nagtitinda|ibinebenta|binibenta)\b")
EXTINGUISHER = r"(?:fire )?extinguisher"
REQUIRED_EXTINGUISHER = re.compile(
    rf"\b{EXTINGUISHER}\b\s*(?:[,;.]\s*)?(?:(?:is|was)\s+)?(?:required|mandatory|kailangan)\b"
    rf"|\b(?:requires?|required|mandatory|kailangang|dapat may|must (?:keep|have|provide|maintain))"
    rf"\s+(?:(?:a|an|the|ng|isang)\s+)?(?:working\s+)?{EXTINGUISHER}\b"
)
NOT_REQUIRED = re.compile(r"\b(?:not required|no requirement|(?:hindi|di) (?:kailangan|required))\b")
MISSING_EXTINGUISHER = re.compile(
    r"\b(?:no|missing|walang|without)\s+(?:a |an )?(?:working |functional )?(?:fire )?extinguisher\b"
    r"(?!\s+(?:(?:is|was|were)\s+)?(?:missing|absent))"
    r"|\bextinguisher\s+(?:is |was )?(?:missing|absent)\b"
)
NEGATED_EQUIPMENT_FAILURE = re.compile(r"\bno (?:fire )?extinguisher (?:is |was |were )?(?:missing|absent)\b")
WORKING_EXTINGUISHER = re.compile(r"\b(?:working|functional|serviceable|gumaganang)\s+(?:fire )?extinguisher\b|\bextinguisher\s+(?:was |is )?(?:tested and working|passed (?:its|the) check)\b")
LEASE_TRANSFER = re.compile(
    r"\b(?:vendor|stallholder|tenant|lessee|tindero)\s+(?:(?:was|is|has|had)\s+)?"
    r"(?:subleas(?:e[ds]?|ing)|sublet(?:ting)?)\b|\bpinapaupahan\s+ng\s+(?:vendor|tindero|stallholder)\b"
)
VERIFIED_CONSENT = re.compile(
    r"\b(?:lessor|market office)\s+(?:confirmed|verified)\s+(?:that\s+)?"
    r"(?:(?P<denied>no|without)\s+)?(?:the\s+)?(?:written\s+)?(?:consent|approval)\b"
    r"(?!\s+(?:(?:was|is)\s+)?(?:required|necessary|withdrawn))"
)
ASSIGNED_OCCUPANCY = re.compile(
    r"\b(?:market office|award record|stall award)\s+(?:confirmed|verified|shows?)\s+(?:that\s+)?"
    r"(?:the )?(?:actual )?(?:occupant|person (?:using|occupying) the stall)\s+(?:was|is)\s+"
    r"(?:(?P<denied>not)\s+)?(?:the awardee|an authorized (?:occupant|helper))\b"
)


def scale_test(text):
    quantities = [item for item in QUANTITY.finditer(text) if UNIT_DIMENSIONS[item[2]] == "mass"]
    references = [item for item in quantities if WEIGHT_REFERENCE.match(text[item.end():])]
    if not references or not SCALE.search(text):
        return None
    if len(references) != 1 or len(quantities) != 2:
        return "insufficient", "scale_test_roles_unresolved"
    reference = references[0]
    reading = next(item for item in quantities if item is not reference)
    if not (READING_BEFORE.search(text[:reading.start()]) or READING_AFTER.match(text[reading.end():])):
        return "insufficient", "scale_test_reading_unresolved"
    expected = Decimal(reference[1]) * UNITS[reference[2]]
    actual = Decimal(reading[1]) * UNITS[reading[2]]
    if expected <= 0:
        return "insufficient", "invalid_reference_weight"
    return ("compliant" if actual == expected else "supported"), "scale_test_comparison"


def expiry_state(code, text):
    if code == "Sanitation" and (not SALE.search(text) or WITHDRAWN.search(text) or NEGATED_USE.search(text)):
        return None
    if code == "Permit & Licensing" and (not PERMIT_USE.search(text) or NEGATED_USE.search(text)):
        return None
    expires, checked = list(EXPIRY.finditer(text)), INSPECTION.findall(text)
    candidates = expires or list(EXPLICIT_EXPIRY.finditer(text))
    if len(candidates) != 1:
        return None
    expiry = candidates[0]
    prefix = text[:expiry.start()]
    if EXPIRY_QUALIFIER.search(prefix) or PROSPECTIVE_EXPIRY.search(prefix):
        return None
    subject = max(
        ((match.end(), category) for category, pattern in EXPIRY_OBJECTS.items()
         for match in pattern.finditer(prefix)),
        default=None,
    )
    if subject is None or subject[1] != code or expiry.start() - subject[0] > 45:
        return None
    if not expires:
        return "supported", "explicit_expiry_during_observed_activity"
    if len(checked) != 1:
        return "insufficient", "missing_or_ambiguous_inspection_date"
    try:
        expired = date.fromisoformat(expiry[1].replace(" ", "-")) < date.fromisoformat(checked[0].replace(" ", "-"))
    except ValueError:
        return "insufficient", "invalid_calendar_date"
    # A current date alone cannot establish that the permit covers the activity.
    return ("supported", "expired_during_observed_activity") if expired else None


def structured_state(code, incident):
    text = incident.context
    if code == "WeightMeasures":
        issue = description_evidence_issue(text)
        if incident.weight_blocked or issue or UNRESOLVED.search(text):
            return "insufficient", issue or "weight_evidence_unresolved"
        comparison = scale_test(text)
        if comparison:
            return comparison
        outcome, reason, _ = described_weight_outcome(text)
        states = {"violation": "supported", "compliant": "compliant", "unknown": "insufficient"}
        return states[outcome], reason or "documented_weight_evidence"
    if code in EXPIRY_OBJECTS:
        return expiry_state(code, text)
    if code == "Stall Rental" and LEASE_TRANSFER.search(incident.text):
        statuses = {bool(match["denied"]) for match in VERIFIED_CONSENT.finditer(text)}
        if len(statuses) == 1:
            return ("supported" if statuses.pop() else "compliant"), "verified_lease_consent"
        if statuses:
            return "insufficient", "conflicting_lease_consent"
    if code == "Stall Occupancy":
        statuses = {bool(match["denied"]) for match in ASSIGNED_OCCUPANCY.finditer(text)}
        if len(statuses) == 1:
            return ("supported" if statuses.pop() else "compliant"), "verified_occupant_status"
        if statuses:
            return "insufficient", "conflicting_occupant_status"
    if code == "Stall Management" and REQUIRED_EXTINGUISHER.search(text) and not NOT_REQUIRED.search(text):
        missing = MISSING_EXTINGUISHER.search(incident.text)
        working = next((match for match in WORKING_EXTINGUISHER.finditer(incident.text)
                        if not missing or match.start() >= missing.end() or match.end() <= missing.start()), None)
        if NEGATED_EQUIPMENT_FAILURE.search(incident.text):
            return "insufficient", "equipment_failure_negated"
        if missing and working:
            return "insufficient", "conflicting_equipment_status"
        if missing or working:
            return ("supported" if missing else "compliant"), "required_equipment_status"
    return None
