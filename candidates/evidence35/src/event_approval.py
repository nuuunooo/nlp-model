"""Compare a held vendor event with its documented approval, offline."""

from dataclasses import dataclass
from datetime import date
import re

from .incidents import UNCERTAIN, incident_spans
from .pilot_evidence import GUARD


CATEGORY = "Entertainment Activities"
PERMIT = r"(?:event (?:permit|approval)|(?:standing|multi event) (?:permit|approval)|permit|approval|pahintulot)"
APPROVAL = re.compile(rf"\b{PERMIT}\b")
SCOPE = re.compile(
    rf"\b{PERMIT}\s+(?:(?:is|was|ay|only|lang|lamang|valid|still valid|(?:na )?may bisa)\s+)*"
    r"(?:for|on|from|covers?|allows?|para (?:lang |lamang )?sa|sakop(?: ang)?|mula)\s+(.+)"
)
REVERSED_DATE = re.compile(rf"\bpara (?:lang |lamang )?sa\s+(.+?)\s+ang (?:\w+ )?{PERMIT}\b")
APPROVED_DATES = re.compile(r"\b(?:approved|authorized) dates?\s+(?:(?:is|are|was|were)\s+)?(.+)")
OCCURRENCE = re.compile(
    r"\b(?:held|hosted|staged|ran|performed|nagdaos|idinaos|isinagawa|itinanghal|ginawa|"
    r"nagpatuloy|nagpa\s*(?:concert|show|palabas)|nag(?:daos|tanghal)|ni stage|nagdagdag)\b"
)
USED_APPROVAL = re.compile(
    r"\b(?:used|reused|ginamit|muling ginamit|ni reuse)\b\s+(.+?)\s+"
    r"(?:to (?:hold|stage|run|host)|para (?:mag\s*(?:daos|tanghal)|magpa\s*daos))\b\s+(.+)"
)
INCOMPLETE = re.compile(
    r"\b(?:daw|raw|planned?|scheduled|proposed|alleged|unconfirmed|pending|would have|"
    r"couldn t (?:read|verify|check)|can t (?:read|verify|check)|unreadable|"
    r"di (?:nabas[ae]|nakita|na check|pa makita|ma verify)|hindi (?:nabas[ae]|nakita)|"
    r"not (?:readable|available|on hand)|for (?:another|the other) (?:stall|vendor)|"
    r"respectively|separate (?:permit|approval)|another (?:permit|approval)|"
    r"amend(?:ed|ment)|renew(?:ed|al)|cancel(?:led|ed)|revoked|expired|suspended|"
    r"and (?:others|more)|among others|at iba pa|unless|except|maliban|subject to)\b"
)
NO_EVENT = re.compile(rf"\b(?:no|not|never|walang|di|hindi)\s+(?:\w+\s+){{0,3}}{OCCURRENCE.pattern}")
UNUSABLE_PERMIT = re.compile(rf"\b(?:no|walang|old|previous|draft|proposed)\s+{PERMIT}\b")
VENDOR = re.compile(r"\b(?:vendors?|sellers?|stallholders?|tindero|tindera|may puwesto|may pwesto)\b")
DIFFERENT_EVENT = re.compile(
    r"(?:(?:a |an )?(?:different|another) event|ibang (?:event|palabas|pagtatanghal))"
    r"(?: (?:only|lang|lamang))?[.!]?"
)
STANDING = re.compile(r"\b(?:standing|multi event|recurring|pang serye)\b")
VALID = re.compile(r"\b(?:valid|active|current|may bisa|bisa pa)\b")
CURRENT_EVENT = re.compile(
    r"^(?:this (?:event|show|concert)(?: (?:today|on .+))?|"
    r"(?:ang )?(?:event|palabas|concert) na ito(?: ngayong araw)?)\s*[.!]?$"
)
STALL = re.compile(r"\b(?:stall|st|puwesto)\.?\s+([a-z]?\s*\d+)\b")
JOIN = re.compile(r"(?:[,;]|\b(?:but|pero|however|whereas|under (?:a |the )?|using (?:a |the )?))\s*$")
CONTRAST = re.compile(r"\b(?:but|pero|however|whereas)\b")

EVENT_NAMES = {
    "concert": r"concerts?|konsiyerto(?:ng)?|live bands?",
    "cooking demo": r"cooking demo(?:nstration)?|demo sa pagluluto",
    "raffle": r"raffle(?: draw)?|bunutan",
    "dance": r"dance (?:competitions?|contests?|shows?)|paligsahan sa sayaw|palabas na sayaw|sayawan",
    "blood drive": r"blood drive|blood donation",
    "variety show": r"variety show",
    "talent show": r"talent show|paligsahan sa talento",
    "karaoke": r"karaoke|videoke",
    "filming": r"film shoot|video shoot(?:ing)?|filming|taping",
    "bingo": r"bingo",
    "magic show": r"magic shows?|palabas ng mahika",
    "puppet show": r"puppet shows?",
}
EVENT_KIND = re.compile("|".join(
    rf"(?P<kind{i}>\b(?:{pattern})\b)" for i, pattern in enumerate(EVENT_NAMES.values())
))
KINDS = tuple(EVENT_NAMES)
EVENT_TOPIC = re.compile(rf"(?:{EVENT_KIND.pattern})|\b(?:event|show|performance|palabas|pagtatanghal)\b")
MONTHS = (
    "january enero jan ene", "february pebrero feb peb", "march marso mar",
    "april abril apr abr", "may mayo", "june hunyo jun hun", "july hulyo jul hul",
    "august agosto aug ago", "september setyembre september sep sept set",
    "october oktubre oct okt", "november nobyembre nov nob", "december disyembre dec dis",
)
MONTH_NUMBER = {word: index for index, names in enumerate(MONTHS, 1) for word in names.split()}
MONTH = "|".join(MONTH_NUMBER)
DATE_DASH = re.compile(
    rf"(?<=\d)(?:\s*[–—]\s*|\s+-\s+|-(?=(?:{MONTH})\b|20\d{{2}}-))"
    rf"(?=\s*(?:\d|(?:{MONTH})\b))", re.I,
)
CALENDAR_DATE = re.compile(
    rf"\b(?:(?P<iso_year>20\d{{2}})\s+(?P<iso_month>\d{{1,2}})\s+(?P<iso_day>\d{{1,2}})"
    rf"|(?P<month_first>{MONTH})\s+(?P<day_second>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<year_last>20\d{{2}}))?"
    rf"|(?P<day_first>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month_second>{MONTH})(?:,?\s+(?P<year_second>20\d{{2}}))?)\b"
)
ORDINAL = re.compile(r"\b(?:ika\s+(\d{1,2})|(\d{1,2})(?:st|nd|rd|th))\b")
RANGE = re.compile(r"\b(?:to|through|until|hanggang|thru)\b")
DATE_JOIN = re.compile(r"^\s*(?:,\s*(?:(?:and|or|at|o)\s*)?|(?:and|or|at|o)\s*)$")
DATE_TAIL = re.compile(r"^\s*(?:only|lang|lamang)?\s*[.!]?$")
WEEKDAYS = (
    "monday lunes", "tuesday martes", "wednesday miyerkules", "thursday huwebes",
    "friday biyernes", "saturday sabado", "sunday linggo",
)
DAY_NUMBER = {word: index for index, names in enumerate(WEEKDAYS) for word in names.split()}
WEEKDAY = re.compile(r"\b(" + "|".join(DAY_NUMBER) + r")\b")
RECURRING = re.compile(r"\b(?:every|tuwing)\b")
DATE_QUALIFIER = re.compile(r"\b(?:from|until|through|mula|hanggang|next|last|linggo|week|month|year)\b")
APPROVAL_UNVERIFIED = re.compile(
    r"\b(?:unreadable|couldn t (?:read|verify|check)|can t (?:read|verify|check)|"
    r"not verified|di (?:ma)?bas[ae]|di na check|di pa makita|di pa sure|"
    r"hindi nabasa|walang verified dates)\b"
)
OTHER_EVENT_CHECK = re.compile(
    r"\b(?:sound|speaker\w*|amplif\w*|noise|volume|tunog|crowd|capacity|"
    r"audience|spectators?|manonood|guard\w*|security|venue|loading|blocked|"
    r"harang\w*|hours?|oras|end time|start time|limit|walang permit|"
    r"(?:no|without|missing) (?:an? )?(?:event )?(?:permit|approval))\b"
)
EVENT_TAIL = re.compile(
    r"\s*(?:contest\s*)?(?:(?:ang|si)\s+(?:tindero|tindera|vendor)\s*)?"
    r"(?:(?:on|nung|noong)\s*)?[.!]?"
)
WEEKDAY_LIST = re.compile(
    rf"(?:{WEEKDAY.pattern})(?:\s*(?:,|and|at|or|o)\s*(?:{WEEKDAY.pattern}))*"
    r"\s*(?:only|lang|lamang)?\s*[.!]?"
)


@dataclass(frozen=True)
class ApprovalCheck:
    state: str
    reason: str
    evidence: str


def kinds(text):
    return {KINDS[int(match.lastgroup[4:])] for match in EVENT_KIND.finditer(text)}


def dated_values(text):
    """Return calendar dates, using year 2000 for an unstated year."""
    matches = list(CALENDAR_DATE.finditer(text))
    values = []
    for match in matches:
        fields = match.groupdict()
        year = fields["iso_year"] or fields["year_last"] or fields["year_second"]
        month = fields["iso_month"] or MONTH_NUMBER.get(fields["month_first"] or fields["month_second"])
        day = fields["iso_day"] or fields["day_first"] or fields["day_second"]
        try:
            values.append((date(int(year or 2000), int(month), int(day)), year is not None))
        except ValueError:
            return matches, []
    return matches, values


def date_state(observed, allowed):
    actual_matches, actual = dated_values(observed)
    permitted_matches, permitted = dated_values(allowed)
    if recurring := RECURRING.search(allowed):
        weekdays = {DAY_NUMBER[m[1]] for m in WEEKDAY.finditer(allowed)}
        event_weekdays = {DAY_NUMBER[m[1]] for m in WEEKDAY.finditer(observed)}
        if permitted_matches or not weekdays or not WEEKDAY_LIST.fullmatch(allowed[recurring.end():].strip()):
            return "insufficient"
        if len(actual) == 1 and actual[0][1]:
            event_weekdays.add(actual[0][0].weekday())
        if len(event_weekdays) != 1:
            return "insufficient"
        return "compliant" if event_weekdays <= weekdays else "supported"
    if actual_matches or permitted_matches:
        if len(actual_matches) != 1 or not actual or not permitted:
            return "insufficient"
        value, has_year = actual[0]
        if any(has_year != dated for _, dated in permitted):
            return "insufficient"
        if not DATE_TAIL.fullmatch(allowed[permitted_matches[-1].end():]):
            return "insufficient"
        ranges = [allowed[a.end():b.start()] for a, b in zip(permitted_matches, permitted_matches[1:])]
        if len(permitted) == 2 and RANGE.fullmatch(ranges[0].strip()):
            start, end = (day for day, _ in permitted)
            if start > end:
                return "insufficient"
            return "compliant" if start <= value <= end else "supported"
        if not all(DATE_JOIN.fullmatch(gap) for gap in ranges):
            return "insufficient"
        return "compliant" if value in {day for day, _ in permitted} else "supported"

    actual_ordinals = list(ORDINAL.finditer(observed))
    approved_ordinals = list(ORDINAL.finditer(allowed))
    actual_days = {int(m[1] or m[2]) for m in actual_ordinals}
    allowed_days = {int(m[1] or m[2]) for m in approved_ordinals}
    if (len(actual_ordinals) == len(approved_ordinals) == 1 and not RANGE.search(allowed)
            and DATE_TAIL.fullmatch(allowed[approved_ordinals[0].end():])):
        if not all(1 <= day <= 31 for day in actual_days | allowed_days):
            return "insufficient"
        # A different day disproves a single approved date even if the month is unstated.
        if actual_days != allowed_days:
            return "supported"
    return "insufficient" if actual_days or allowed_days else None


def compare(observed, allowed, approval, evidence):
    actual, permitted = kinds(observed), kinds(allowed)
    if len(actual) > 1 or not EVENT_TOPIC.search(observed):
        return ApprovalCheck("insufficient", "observed_event_not_identified", evidence)
    if STANDING.search(approval) and not VALID.search(approval):
        return ApprovalCheck("insufficient", "standing_approval_validity_unverified", evidence)
    if DATE_TAIL.fullmatch(allowed) or INCOMPLETE.search(allowed):
        return ApprovalCheck("insufficient", "approval_scope_unverified", evidence)
    if DIFFERENT_EVENT.fullmatch(allowed):
        return ApprovalCheck("supported", "approval_for_different_event", evidence)
    if actual and permitted and actual.isdisjoint(permitted):
        names = CALENDAR_DATE.sub("", allowed)
        parts = [part for part in re.split(r",|\b(?:and|or|at|o)\b", names) if part.strip(" .")]
        if all(kinds(part) for part in parts):
            return ApprovalCheck("supported", "approval_for_different_event", evidence)
        return ApprovalCheck("insufficient", "approval_scope_unverified", evidence)
    dates = date_state(observed, allowed)
    if dates == "supported":
        return ApprovalCheck(dates, "outside_approved_dates", evidence)
    scope_matches = (actual and actual <= permitted) or CURRENT_EVENT.fullmatch(allowed)
    if (dates == "compliant" and (not permitted or scope_matches)
            or dates is None and scope_matches and not DATE_QUALIFIER.search(allowed)):
        return ApprovalCheck("compliant", "within_documented_approval", evidence)
    return ApprovalCheck("insufficient", "approval_scope_or_date_unverified", evidence)


def approval_scope(text):
    if UNUSABLE_PERMIT.search(text):
        return None
    for pattern in (REVERSED_DATE, APPROVED_DATES, SCOPE):
        if match := pattern.search(text):
            return match[1].strip(" ,;")
    return None


def assess_event_approval(description, normalize):
    """Read one unambiguous event and approval pair, keeping existing findings separate."""
    description = DATE_DASH.sub(" to ", description)
    units = incident_spans(description, normalize)
    normalized = normalize(description)
    if not APPROVAL.search(normalized) or not EVENT_TOPIC.search(normalized):
        return None
    fallback = ApprovalCheck("insufficient", "no_verified_event_approval_pair", normalized)
    observations = []
    for i, unit in enumerate(units):
        text = unit.text
        if unit.blocked or unit.is_requirement or GUARD.search(text) or INCOMPLETE.search(text) or NO_EVENT.search(text):
            continue
        actor = VENDOR.search(text) or STALL.search(text)
        if not actor:
            continue
        if (used := USED_APPROVAL.search(text)) and APPROVAL.search(used[1]) and not UNUSABLE_PERMIT.search(used[1]):
            observations.append((i, used[2], used[1], text))
            continue
        action = OCCURRENCE.search(text)
        if action is None:
            continue
        # Keep a permit clause apart from the observed event, regardless of its order.
        if approval := APPROVAL.search(text):
            if approval.start() > action.start():
                observed, permit_text = text[:approval.start()], text[approval.start():]
                if not JOIN.search(observed):
                    continue
                observed = JOIN.sub("", observed).strip(" ,;")
            else:
                observed, permit_text = text[action.start():], text[:action.start()]
                permit_text = CONTRAST.split(permit_text)[0].strip(" ,;")
        else:
            observed, permit_text = text, ""
        if EVENT_TOPIC.search(observed):
            observations.append((i, observed, approval_scope(permit_text), permit_text))
    if len(observations) != 1:
        return fallback
    index, observed, allowed, approval = observations[0]
    unit = units[index]
    neighbors = [other for i, other in enumerate(units) if abs(i - index) == 1]
    if unit.blocked or any(other.blocked and APPROVAL.search(other.text) for other in neighbors):
        return fallback
    if allowed is None:
        scopes = [(scope, other.text) for other in neighbors
                  if not (other.blocked or INCOMPLETE.search(other.text) or UNCERTAIN.search(other.text))
                  and (scope := approval_scope(other.text))]
        if len(scopes) != 1:
            return fallback
        allowed, approval = scopes[0]
    evidence = f"{observed}; {approval}" if approval != unit.text else unit.text
    observed_stalls = {re.sub(r"\s+", "", match[1]) for match in STALL.finditer(observed)}
    approval_stalls = {re.sub(r"\s+", "", match[1]) for match in STALL.finditer(approval)}
    if len(observed_stalls) > 1 or not approval_stalls <= observed_stalls or any(
            other.text != approval and approval_scope(other.text) is not None
            for other in neighbors):
        return fallback
    if any(other.blocked and APPROVAL.search(other.text)
           for other in units[index + 1:index + 3]):
        return fallback
    if INCOMPLETE.search(evidence) or UNCERTAIN.search(evidence) or GUARD.search(evidence):
        return fallback
    return compare(observed, allowed, approval, evidence)


def approval_only_note(description, check, normalize):
    """Allow a local veto only when the note contains no other event check."""
    units = incident_spans(DATE_DASH.sub(" to ", description), normalize)
    if not units or len(units) > 2 or any(OTHER_EVENT_CHECK.search(unit.text) for unit in units):
        return False
    if len(units) == 1:
        used = USED_APPROVAL.search(units[0].text)
        observed = used[2] if used and check.state == "compliant" else ""
    else:
        permits = [unit.text for unit in units if APPROVAL.search(unit.text)]
        if len(permits) != 1:
            return False
        permit, = permits
        if check.state == "insufficient" and not APPROVAL_UNVERIFIED.search(permit):
            return False
        observed = next(unit.text for unit in units if unit.text != permit)
        if not OCCURRENCE.search(observed):
            return False
    types = list(EVENT_KIND.finditer(observed))
    if len(types) != 1:
        return False
    tail = observed[types[0].end():]
    tail = WEEKDAY.sub("", CALENDAR_DATE.sub("", tail))
    return bool(EVENT_TAIL.fullmatch(tail))


def with_event_approval(description, baseline_codes, normalize):
    check = assess_event_approval(description, normalize)
    findings = set(baseline_codes)
    if check and check.state == "supported":
        findings.add(CATEGORY)
    elif check and CATEGORY in findings and approval_only_note(description, check, normalize):
        findings.remove(CATEGORY)
    return findings, check
