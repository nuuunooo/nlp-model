"""Compare independently recorded masses using grams."""

from decimal import Decimal, InvalidOperation
import re
import unicodedata


WEIGHT_CODE = "WeightMeasures"
MASS_UNITS = {"g": Decimal(1), "kg": Decimal(1000)}
UNCERTAIN_EVIDENCE = (
    ("reference_scale_unreliable", re.compile(
        r"\b(?:sira|depektibo|hindi calibrated)\b.{0,75}\b(?:timbangan bayan|reference scale)\b"
        r"|\b(?:timbangan bayan|reference scale)\b.{0,75}\b(?:sira|depektibo|faulty|broken|"
        r"unreliable|uncalibrated|not calibrated|failed)\b", re.I)),
    ("weighing_conditions_unresolved", re.compile(
        r"\b(?:drained|net|tare)\s+weight\s+(?:was\s+)?not\s+(?:taken|checked|verified|recorded)\b"
        r"|\b(?:tare|drained weight|net weight)\b.{0,35}\b(?:unknown|uncertain|unverified|disputed)\b"
        r"|\b(?:hindi|di)\s+(?:na)?(?:tare|tinare|sinala|naalis ang yelo)\b", re.I)),
    ("transaction_disputed", re.compile(
        r"\b(?:declared|ordered|purchased)\s+(?:quantity|weight)\b.{0,35}\b(?:disputed|unknown|uncertain)\b"
        r"|\baway\b.{0,55}\bkung\b", re.I)),
)


def description_evidence_issue(description):
    text = unicodedata.normalize("NFKC", description).lower()
    text = re.sub(r"[-_\s]+", " ", text)
    return next((reason for reason, pattern in UNCERTAIN_EVIDENCE if pattern.search(text)), None)


def reweigh_reliability_issue(evidence, description):
    issue = description_evidence_issue(description) or evidence.get("evidence_issue")
    if issue:
        return issue
    if not str(evidence.get("scale_check_reference") or "").strip():
        return "reference_scale_check_missing"
    if evidence.get("transaction_verified") is not True:
        return "transaction_not_verified"
    if evidence.get("conditions_verified") is not True:
        return "weighing_conditions_not_verified"
    return None


def mass_in_grams(quantity, unit):
    try:
        value = Decimal(str(quantity))
        factor = MASS_UNITS[unit]
    except (InvalidOperation, KeyError) as exc:
        raise ValueError("A reweigh needs a positive quantity in g or kg") from exc
    # Keep enough precision for inspection measurements without silently rounding input.
    if not value.is_finite() or not 0 < value < 10**9 or value.as_tuple().exponent < -6:
        raise ValueError("A reweigh needs a positive quantity below 1 billion with at most six decimals")
    return value * factor
