"""Compare recorded stall operating days with a stated minimum."""

from dataclasses import dataclass
import re

from .incidents import UNCERTAIN, incident_spans
from .vendor_id_stall import SITE, locations


CATEGORY = "Stall Occupancy"
WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "isang": 1, "dalawang": 2, "tatlong": 3, "apat": 4, "limang": 5,
    "anim": 6, "pitong": 7, "walong": 8, "siyam": 9, "sampung": 10,
}
NUMBER = r"(?:\d{1,2}|" + "|".join(WORDS) + ")"
DAYS = rf"\b(?P<days>{NUMBER})(?:\s+(?:na|operating|working|business))?\s+(?:days?|araw)\b"
CADENCE = (
    r"\s+(?:(?:only|lang|lamang)\s+)?(?:(?:a|per|each|every|kada|bawat|sa isang)\s+"
    r"(?P<period>week|linggo|month|buwan)|(?P<adverb>weekly|monthly))\b"
)
SLASH_CADENCE = re.compile(r"\b(days?|araw)\s*/\s*(week|month|linggo|buwan)\b", re.I)
MINIMUM = re.compile(
    r"\b(?:at least|min(?:imum)?(?: of)?|no fewer than|not less than|"
    rf"hindi (?:na )?bababa sa|di bababa sa|di kukulangin sa)\s+{DAYS}{CADENCE}"
)
DAY_COUNT = re.compile(DAYS + rf"(?:{CADENCE})?")
REQUIREMENT = re.compile(r"\b(?:must|shall|require[sd]?|requirement|min(?:imum)?|dapat|kailangan(?:g)?)\b")
RECORD = re.compile(
    r"\b(?:(?:attendance|opening|operating|operation|section|stall|weekly|monthly)\s+"
    r"(?:log(?:book)?|records?|talaan)|log(?:book)?|(?:attendance|operating days) sa talaan)\b"
)
OPERATOR = re.compile(r"\b(?:awardee|stallholder|lessee|may puwesto|may pwesto)\b")
STALL = re.compile(r"\b(?:stall|store|puwesto|pwesto|tindahan)\b")
NUMBERED_STALL = re.compile(SITE)
PERSONAL = re.compile(r"\b(?:personally|personal(?: na)?|mismo|sariling)\b")
OPERATED = re.compile(
    r"\b(?:operat(?:e[ds]?|ing)|ran|run|running|work(?:ed|s|ing)?|trading|selling|"
    r"nagtrabaho|nag\s*wo\s*work|nagpatakbo|pinapatakbo|patakbuhin|nagtitinda|nagbebenta)\b"
)
ATTENDANCE = re.compile(r"\b(?:attendance|present|came|pumunta|pumupunta|dumalo|pumasok)\b")
OPEN = re.compile(r"\b(?:open(?:ed|ing)?|operat(?:e[ds]?|ing)|bukas|nagbukas|binuksan)\b")
PROXY = re.compile(r"\b(?:helpers?|staff|employees?|assistants?|katulong|tauhan|bantay)\b")
PROXY_CLAUSE = re.compile(
    rf"\b(?:while|habang)\s+(?:(?:the|mga|registered|rehistradong|authorized)\s+)*{PROXY.pattern}"
)
NO_OPERATION = re.compile(
    r"\b(?:did not (?:work|open|operate)|not open|absent|never (?:opened|worked)|"
    r"di nag\s*(?:wo\s*work|trabaho|bukas)|hindi nag(?:trabaho|bukas)|"
    r"wala ang (?:awardee|stallholder|lessee)|sarado (?:buong|noong))\b"
)
LAST_PERIOD = re.compile(
    r"\b(?:last|previous|completed|full|closed|nakaraang|nakalipas na|buong)\s+"
    r"(?P<period>week|linggo|month|buwan)\b"
)
PAST_SPAN = re.compile(
    rf"\b(?:for (?:the )?(?:past |last )?|past |last |nang |nakaraang |nakalipas na )"
    rf"(?:{NUMBER}|an?|the)\s+(?:weeks?|linggo|months?|buwan)\b"
    r"|\b(?:isang|buong)\s+buwang?\b|\b(?:past|last|nakaraang)\s+(?:week|linggo|month|buwan)\b"
)
REVIEW_SPAN = re.compile(
    rf"\b(?P<count>{NUMBER}|an?)\s+(?P<span>weeks?|linggo|months?|buwang?)\b"
)
WEEKDAY = r"(?:mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|lunes|martes|miyerkules|huwebes|biyernes|sabado|linggo)"
ONLY_WEEKDAY = re.compile(
    rf"\b(?:only on {WEEKDAY}|tuwing {WEEKDAY}\s+(?:lamang|lang)|{WEEKDAY}\s+(?:lang|lamang))\b"
)
INCOMPLETE = re.compile(
    r"\b(?:daw|raw|reportedly|rumou?r|maybe|estimate[ds]?|about|approximately|around|halos|"
    r"partial|incomplete|missing (?:pages?|entries|days?|records?|logs?)|"
    r"(?:pages?|entries|records?|logs?)\s+(?:(?:are|were|is|was)\s+)?missing|"
    r"blank|blangko|kulang (?:ang |yung )?(?:log|talaan|entries)|di kumpleto|hindi kumpleto|"
    r"nawawalang (?:pahina|entry)|unreadable|di mabasa|not checked|not verified|"
    r"di na check|di alam|so far|to date|as of|this week|this month|ngayong linggo|ngayong buwan|"
    r"still ongoing|average[ds]?|on average|at least|no more than|up to|"
    r"scheduled|planned|expected|projected|forecast|balak|planong|not available|unavailable|unlogged|"
    r"(?:checked|reviewed|covered) (?:for )?(?:only )?\d+ days?)\b"
)
NON_OPERATING_COUNT = re.compile(r"\b(?:absent|leave|off duty|days? (?:off|left|remaining)|sarado|walang pasok)\b")
EXCEPTION = re.compile(
    r"\b(?:exempt\w*|waive[dsr]?|approved (?:leave|closure)|authorized (?:leave|closure)|"
    r"allowed leave|excused|pinayagang magsara|suspension|temporar(?:y|ily) closed|"
    r"not required|no requirement|hindi kailangan|di kailangan|unless|except|maliban|if|kung|"
    r"(?:another|neighboring|other|ibang) (?:stall|store|puwesto|pwesto|awardee))\b"
)
UNVERIFIED_FOLLOWUP = re.compile(r"^(?:it|this|that|the log|the record|ito|iyon|yung log|ang talaan)\b")


@dataclass(frozen=True)
class OperatingDaysCheck:
    state: str
    reason: str
    evidence: str
    recorded_days: int | None = None
    minimum_days: int | None = None
    period: str | None = None
    basis: str | None = None


def number(value):
    return int(value) if value.isdigit() else WORDS[value]


def period(value):
    return "week" if value in {"week", "weekly", "linggo"} else "month"


def rule_basis(text):
    if PERSONAL.search(text) or (OPERATOR.search(text) and (ATTENDANCE.search(text)
                                 or re.search(r"\b(?:work|operate|run|magtrabaho|patakbuhin)\b", text))):
        return "personal_attendance" if ATTENDANCE.search(text) and not OPERATED.search(text) else "personal_operation"
    if OPEN.search(text) or STALL.search(text):
        return "stall_operation"
    return None


def recorded_days(text, cadence):
    counts = list(DAY_COUNT.finditer(text))
    completed = {period(match["period"]) for match in LAST_PERIOD.finditer(text)}
    if counts and (NO_OPERATION.search(text) or NON_OPERATING_COUNT.search(text)
                   or re.search(r"\bclosed\s+(?:for\s+)?(?:\d+|one|two|three|four|five|six|seven)\s+days?\b", text)):
        return None
    if len(counts) == 1:
        item = counts[0]
        item_period = item["period"] or item["adverb"]
        if item_period and period(item_period) == cadence and PAST_SPAN.search(text):
            return number(item["days"])
        if not item_period and completed == {cadence}:
            return number(item["days"])
    if counts:
        return None
    if cadence == "week" and ONLY_WEEKDAY.search(text) and PAST_SPAN.search(text):
        return 1
    if absence := NO_OPERATION.search(text):
        if completed == {cadence}:
            return 0
        if cadence == "week":
            for span in REVIEW_SPAN.finditer(text):
                if span.start() > absence.end() + 55 or span.end() < absence.start() - 25:
                    continue
                weeks = span["span"] in {"week", "weeks", "linggo"}
                size = 1 if span["count"] in {"a", "an"} else number(span["count"])
                if size >= (2 if weeks else 1):
                    return 0
    return None


def apply_minimum(observed, rule, match, evidence):
    basis = rule_basis(rule)
    cadence = period(match["period"] or match["adverb"])
    minimum = number(match["days"])
    actual = recorded_days(observed, cadence)
    maximum = 7 if cadence == "week" else 31
    if basis is None or actual is None or not (0 <= actual <= maximum and 1 <= minimum <= maximum):
        return OperatingDaysCheck("insufficient", "incomplete_or_incomparable_operating_record", evidence)
    if basis == "stall_operation":
        usable = OPEN.search(observed) or NO_OPERATION.search(observed) and STALL.search(observed)
        if not usable or OPERATOR.search(observed) and not STALL.search(observed):
            return OperatingDaysCheck("insufficient", "stall_open_days_unverified", evidence)
    else:
        subject_clause = PROXY_CLAUSE.split(observed, maxsplit=1)[0]
        if not OPERATOR.search(subject_clause) or PROXY.search(subject_clause):
            return OperatingDaysCheck("insufficient", "awardee_days_unverified", evidence)
        if not (OPERATED.search(observed) or ATTENDANCE.search(observed) or NO_OPERATION.search(observed)):
            return OperatingDaysCheck("insufficient", "awardee_activity_unverified", evidence)
        # Presence can bound personal operating days from above, but does not prove operation.
        if basis == "personal_operation" and actual >= minimum and not OPERATED.search(observed):
            return OperatingDaysCheck("insufficient", "presence_does_not_verify_operation", evidence)
    state = "supported" if actual < minimum else "compliant"
    reason = "below_stated_minimum" if state == "supported" else "meets_stated_minimum"
    return OperatingDaysCheck(state, reason, evidence, actual, minimum, cadence, basis)


def assess_operating_days(description, normalize):
    units = incident_spans(SLASH_CADENCE.sub(r"\1 per \2", description), normalize)
    check = None
    for index, unit in enumerate(units):
        if unit.is_requirement or not RECORD.search(unit.text):
            continue
        neighbors = units[max(0, index - 1):index] + units[index + 1:index + 2]
        minimums = [(other, match) for other in [unit, *neighbors] if REQUIREMENT.search(other.text)
                    for match in MINIMUM.finditer(other.text)]
        if not minimums:
            if (OPERATOR.search(unit.text) or STALL.search(unit.text)) and (DAY_COUNT.search(unit.text) or INCOMPLETE.search(unit.text)):
                check = OperatingDaysCheck("insufficient", "minimum_or_record_unverified", unit.text)
            continue
        check = OperatingDaysCheck("insufficient", "minimum_or_record_unverified", unit.text)
        if len(minimums) != 1:
            continue
        rule, minimum = minimums[0]
        if unit.blocked or rule.blocked or UNCERTAIN.search(unit.text) or UNCERTAIN.search(rule.text):
            continue
        evidence = unit.text if rule is unit else f"{unit.text} {rule.text}"
        if len(locations(evidence, NUMBERED_STALL)) > 1 or EXCEPTION.search(evidence):
            continue
        if any((RECORD.search(other.text) or UNVERIFIED_FOLLOWUP.search(other.text))
               and (other.blocked or INCOMPLETE.search(other.text) or EXCEPTION.search(other.text))
               for other in [*neighbors, *units[index + 2:index + 3]] if other is not rule):
            continue
        observed = unit.text
        if rule is unit:
            observed = unit.text[:minimum.start()] + unit.text[minimum.end():]
        if INCOMPLETE.search(observed):
            continue
        check = apply_minimum(observed, rule.text, minimum, evidence)
        if check.state == "supported":
            return check
    return check


def with_operating_days(description, baseline_codes, normalize):
    check = assess_operating_days(description, normalize)
    findings = set(baseline_codes)
    if check and check.state == "supported":
        findings.add(CATEGORY)
    return findings, check
