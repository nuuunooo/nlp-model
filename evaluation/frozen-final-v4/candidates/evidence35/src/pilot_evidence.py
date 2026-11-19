"""Additional incident facts evaluated separately from existing pilot findings."""

import re

from .incidents import UNCERTAIN
from .structured_evidence import structured_state


STRUCTURED_ROUTES = {
    "scale_test_comparison", "explicit_expiry_during_observed_activity",
    "expired_during_observed_activity", "required_equipment_status",
    "verified_lease_consent", "verified_occupant_status",
}
GUARD = re.compile(
    r"\b(?:if|kung|alleged|hypothetical|example only|did not|never|was not|"
    r"cleared before|removed before|naalis na|naayos na|walang paglabag|no violation)\b"
)
VENDOR = re.compile(r"\b(?:vendor|seller|stallholder|tindero|tindera|may puwesto)\b")
PLACEMENT = re.compile(r"\b(?:hung|tied|strung|parked|stacked|placed|nagsabit|isinabit|nagtali|itinali|pinark|isinalansan|nagpatong)\b")
PASSAGE = re.compile(r"\b(?:aisle|passage|walkway|pasilyo|daanan|fire exit|emergency exit)\b")
PASSAGE_IMPACT = re.compile(
    r"\b(?:shoppers? (?:had to duck|could not pass)|could not pass|blocked the (?:aisle|exit)|"
    r"hindi makadaan|napapayuko|kailangang yumuko|nahaharangan)\b"
)
INSPECTION_INTERFERENCE = re.compile(
    r"\b(?:grabbed|snatched|seized|inagaw|hinablot)\b.{0,50}"
    r"\b(?:test weight[s]?|scale|timbangan|measure|medida|tape|thermometer(?: probe)?)\b"
    r".{0,28}\b(?:of (?:the )?|from (?:the )?(?:hand[s]? of (?:the )?)?|ng )"
    r"(?:inspector|inspektor|enforcer)\b"
)


def eligible_incident(unit):
    return (not unit.blocked and not unit.is_requirement and "?" not in unit.context
            and not UNCERTAIN.search(unit.context) and not GUARD.search(unit.context))


def targeted_evidence(unit):
    """Return a category only when the incident documents the policy-relevant act."""
    if not eligible_incident(unit) or not VENDOR.search(unit.text):
        return
    observed = unit.text
    if PLACEMENT.search(observed) and PASSAGE.search(observed) and PASSAGE_IMPACT.search(observed):
        yield "Obstruction", "observed_passage_impact"
    if INSPECTION_INTERFERENCE.search(observed) and not re.search(r"\b(?:hindi|di|authorized to|with permission)\b", observed):
        yield "Resisting Authority", "observed_inspection_interference"


def shared_evidence(unit, nominations):
    """Limit shared verification to facts with explicit roles and a nominated category."""
    if not eligible_incident(unit):
        return
    for code in nominations:
        verdict = structured_state(code, unit)
        if verdict and verdict[0] == "supported" and verdict[1] in STRUCTURED_ROUTES:
            yield code, verdict[1]
