"""Check vendor use against a documented repair or safety closure."""

from dataclasses import dataclass
import re

from .event_approval import DATE_DASH, dated_values
from .incidents import UNCERTAIN, incident_spans
from .stall_operating_days import CATEGORY
from .vendor_id_stall import SITE, locations


NUMBERED_STALL = re.compile(SITE)
ACTOR = re.compile(
    r"\b(?:stallholders?|vendors?|sellers?|tindero|tindera|may puwesto|may pwesto|"
    r"repair crew|repair team|contractor|maintenance crew|taga ayos)\b"
)
LOCATION = r"(?:stall|row|store|puwesto|pwesto|tindahan|hanay)"
CLOSED = re.compile(
    rf"\b(?:closed (?:{LOCATION}|for (?:structural )?repairs?)|"
    rf"saradong {LOCATION}|sarado (?:ang )?{LOCATION}|{LOCATION} (?:na )?(?:is |was |still |remains )?(?:closed|sarado)|"
    rf"{LOCATION}[^,.;]{{0,24}}?\b(?:closed|sarado) (?:for|para sa|pa|from|mula)|"
    rf"(?:(?:still|remains|officially) closed|sarado pa|isinara)\b)"
)
REPAIR = re.compile(r"\b(?:repairs?|repair work|pagkukumpuni|inaayos|pag aayos)\b")
AUTHORITY = re.compile(
    r"\b(?:market office|market management|market admin|market administrator|market notice|"
    r"opisina ng palengke|pamunuan ng palengke|posted closure notice|official (?:repair |safety )?closure|"
    r"repair closure order|safety closure order|repair notice|closure notice|utos ng admin|notice ng admin|isinara ng admin)\b"
)
OCCUPY = r"(?:occup(?:y|ied|ying|ancy)|ino\s*occupy|inookupahan|okupahan|okupado|gamitin|use)"
BAN = re.compile(
    rf"\b(?:may not|must not|not allowed to|no|prohibited from|bawal|hindi pinapayagang)\s+"
    rf"(?:(?:be|ang|mag|i)\s+)?(?P<action>{OCCUPY}|entry|access|enter|selling|trading|sell|"
    r"pumasok|pasok|pagtitinda|magtinda)\b(?!\s+(?:restriction|ban|prohibition|rule)\b)"
    rf"|\b(?P<reverse>{OCCUPY}|entry|access|selling|trading|pagtitinda)\s+(?:is |ay )?(?:prohibited|bawal)\b"
)
ACTIONS = {
    "trade": r"selling|trading|sold|nagbebenta|nagtitinda|nagbenta",
    "occupy": r"occupying|occupied|ino\s*occupy|inookupahan|"
              r"(?:moved|put) stock (?:back )?(?:in|into)|stored (?:goods|stock)|binalik[^,.;]{0,25}stock",
    "work": r"worked inside|working inside|nagtatrabaho[^,.;]{0,28}sa loob|nag\s*wo\s*work[^,.;]{0,25}sa loob|"
            r"performed repairs|nag ayos",
    "retrieve": r"retrieved|picked up|collected|kinuha",
    "enter": r"entered|went inside|pumasok",
}
PERMISSION = re.compile(
    r"\b(?:with (?:written |official |market office )?(?:permission|clearance|approval)|"
    r"(?:allowed|authorized|permitted) by (?:the )?(?:market office|market admin)|"
    r"(?:market office|market admin) (?:allowed|authorized|permitted)|"
    r"pinayagan ng (?:market office|admin|opisina ng palengke)|may (?:sulat na )?pahintulot ng admin)\b"
)
GRANT_PURPOSES = {
    "trade": r"(?:to|for|para sa) (?:sell(?:ing)?|trad(?:e|ing)|pagtitinda|magtinda)",
    "occupy": r"(?:to|for|para sa) (?:occupy|occupancy|storage|store stock|okupahan|imbakan)",
    "work": r"(?:to|for|para sa) (?:repair\w*|maintenance|work|pag aayos)",
    "retrieve": r"(?:to|for|para sa) (?:retriev\w*|collect\w*|pick\s*up|kunin|pagkuha)",
    "enter": r"(?:to|for|para sa) (?:entry|enter|access|pagpasok|pumasok)",
}
REPAIR_CREW = re.compile(r"\b(?:repair crew|repair team|contractor|maintenance crew|taga ayos)\b")
AUTHORIZATION_TOPIC = re.compile(r"^(?:(?:the|ang|yung)\s+)?(?:permission|approval|clearance|pahintulot)\b")
USE_LINK = re.compile(r"\b(?:inside|there|in the stall|in the row|at this stall|sa loob|sa puwestong ito|doon)\b")
NON_OBSERVATION = re.compile(
    r"\b(?:(?:to|for|para sa|before|bago|if|kung|planned|scheduled)\s*)$|"
    r"\b(?:was told|was asked|was warned|stopped before|was prevented from)\b"
)
NO_PERMISSION = re.compile(
    r"\b(?:without (?:written |market office )?(?:permission|clearance|approval)|"
    r"no (?:permission|clearance|approval)|walang (?:pahintulot|clearance|approval)|"
    r"denied (?:permission|entry)|di pinayagan)\b"
)
EXCEPTION = re.compile(
    r"\b(?:except|unless|authorized only|only authorized|clearance (?:is )?required|"
    r"with prior permission|maliban|kung may pahintulot)\b"
)
CONDITIONAL_GRANT = re.compile(r"\b(?:except|unless|only|requires?|maliban)\s*$")
LIMITED_GRANT = re.compile(r"\b(?:only|solely|lang|lamang)\b")
INCOMPLETE = re.compile(
    r"\b(?:daw|raw|baka|maybe|reportedly|alleged|claimed|di (?:sure|sigurado|alam|na check|nakita)|"
    r"hindi (?:tiyak|sigurado|alam|nakumpirma)|can't tell|can t tell|couldn t check|"
    r"unverified|unclear|unknown|not confirmed|not verified|not checked|notice missing|dates missing|"
    r"scheduled to close|will close|proposed closure|planong isara|pending approval)\b"
)
NEGATED_OR_OUTSIDE = re.compile(
    r"\b(?:did not (?:enter|sell|trade|occupy)|didn t (?:enter|sell)|hindi (?:pumasok|nagtinda|nagbenta)|"
    r"di (?:pumasok|nagtinda|nagbenta)|"
    r"(?:outside|beside|next to) (?:the )?(?:closed )?(?:stall|row|closure|tape)|"
    r"sa labas ng (?:saradong )?(?:stall|puwesto|pwesto|hanay|tape))\b"
)
PENALTY = re.compile(r"\b(?:suspension|suspended|revoked|penalty|unpaid fine|suspendido|kinansela|multa)\b")
OTHER_LOCATION = re.compile(rf"\b(?:another|different|neighboring|other|ibang|katabing)\s+{LOCATION}\b")
REOPENED = re.compile(
    r"\b(?:(?:closure|order|restriction) (?:was |has been )?(?:lifted|ended|expired)|"
    r"(?:market office|market admin) (?:officially )?reopened|officially reopened|"
    r"no longer closed|binuksan na ng (?:admin|market office)|tapos na ang (?:repair|pagsasara))\b"
)
TEMPORAL = re.compile(
    r"\b(?:from|through|until|between|on|mula|hanggang|noong|last (?:week|month)|kahapon|"
    r"since|effective)\b"
)
UNTIL_REOPENS = re.compile(r"\b(?:until (?:the )?(?:row|stall) reopens|hanggang muling buksan|hanggang mag reopen)\b")
ACTIVE = re.compile(r"\b(?:still closed|remains closed|currently closed|sarado pa|during the closure|habang sarado)\b")
REFERENCE = re.compile(r"^(?:it|this|that|ito|iyon|ang notice|yung notice)\b")


@dataclass(frozen=True)
class RepairClosureCheck:
    state: str
    reason: str
    evidence: str


def actions(text):
    restrictions = list(BAN.finditer(text))
    return {kind for kind, pattern in ACTIONS.items() for match in re.finditer(rf"\b(?:{pattern})\b", text)
            if not any(ban.start() <= match.start() < ban.end() for ban in restrictions)
            and not NON_OBSERVATION.search(text[max(0, match.start() - 36):match.start()])}


def banned_actions(text):
    banned = set()
    for match in BAN.finditer(text):
        action = match["action"] or match["reverse"]
        if action in {"entry", "access", "enter", "pumasok", "pasok"}:
            banned.update(ACTIONS)
        elif action in {"selling", "sell", "trading", "pagtitinda", "magtinda"}:
            banned.add("trade")
        else:
            banned.update(("occupy", "trade", "work"))
    return banned


def closure_timing(observed, notice):
    """Compare explicit dates when present, otherwise require a contemporaneous closure."""
    observed = NUMBERED_STALL.sub(" ", observed)
    notice = NUMBERED_STALL.sub(" ", notice)
    matches, allowed = dated_values(notice)
    actual_matches, actual = dated_values(observed)
    if matches:
        if len(actual_matches) != 1 or not actual or len(matches) != len(allowed) or len(allowed) > 2:
            return None
        value, actual_has_year = actual[0]
        if any(has_year != actual_has_year for _, has_year in allowed):
            return None
        if len(allowed) == 1:
            if not re.search(r"\b(?:closed|sarado)[^,.;]{0,40}\b(?:on|noong)\s*$", notice[:matches[0].start()]):
                return None
            if value == allowed[0][0]:
                return True
            return False if LIMITED_GRANT.search(notice[matches[0].end():]) else None
        connector = notice[matches[0].end():matches[1].start()].strip()
        start, end = (item[0] for item in allowed)
        if connector not in {"to", "through", "hanggang", "until"} or start > end:
            return None
        if value == end and connector in {"until", "hanggang"}:
            return None
        return start <= value <= end
    # A stated period without comparable dates cannot be resolved from a generic closure rule.
    if TEMPORAL.search(UNTIL_REOPENS.sub("", notice)) and not ACTIVE.search(notice):
        return None
    if re.search(r"\b(?:last (?:week|month)|kahapon|noong nakaraan)\b", observed) and not ACTIVE.search(observed):
        return None
    return True


def compare_closure(observed, notice, context, observed_actions, blocked_actions):
    fallback = RepairClosureCheck("insufficient", "closure_status_date_or_permission_unverified", context)
    if REOPENED.search(context):
        return fallback
    # A closed place has official scope through a notice or a stated repair-specific ban.
    official = AUTHORITY.search(context) or (REPAIR.search(context) and bool(blocked_actions))
    if not official:
        return fallback
    timing = closure_timing(observed, notice)
    if timing is None:
        return fallback
    if not timing:
        return RepairClosureCheck("compliant", "observed_use_outside_documented_closure", context)
    permits = [match for match in PERMISSION.finditer(context)
               if not NO_PERMISSION.search(context[max(0, match.start() - 12):match.end()])
               and not CONDITIONAL_GRANT.search(context[:match.start()])]
    if permits:
        permitted = set()
        for grant in permits:
            purpose = context[grant.end():].split(".", 1)[0]
            if REPAIR_CREW.search(purpose) and not REPAIR_CREW.search(observed):
                return fallback
            permitted.update(action for action, pattern in GRANT_PURPOSES.items()
                             if re.search(rf"\b(?:{pattern})\b", purpose))
        if not permitted and len(observed_actions) == 1 and PERMISSION.search(observed):
            permitted = observed_actions.copy()
        if permitted & {"retrieve", "work", "occupy", "trade"}:
            permitted.add("enter")
        if observed_actions <= permitted and not NO_PERMISSION.search(context):
            return RepairClosureCheck("compliant", "observed_access_explicitly_permitted", context)
        if (len(permits) == 1 and permitted and (observed_actions - permitted) & blocked_actions
                and LIMITED_GRANT.search(context[permits[0].end():].split(".", 1)[0])):
            return RepairClosureCheck("supported", "prohibited_use_outside_granted_access", context)
        # Scope of a grant and any additional activity must be unambiguous.
        return fallback
    if EXCEPTION.search(context) and not NO_PERMISSION.search(context):
        return fallback
    if observed_actions & blocked_actions:
        return RepairClosureCheck("supported", "prohibited_use_during_official_closure", context)
    return fallback


def assess_repair_closure(description, normalize):
    units = incident_spans(DATE_DASH.sub(" to ", description), normalize)
    check = None
    for index, unit in enumerate(units):
        if unit.is_requirement or not ACTOR.search(unit.text):
            continue
        observed_actions = actions(unit.text)
        neighbors = units[max(0, index - 1):index] + units[index + 1:index + 2]
        related = [other for other in neighbors if CLOSED.search(other.text) or AUTHORITY.search(other.text)
                   or PERMISSION.search(other.text) or BAN.search(other.text) or REOPENED.search(other.text)
                   or AUTHORIZATION_TOPIC.search(other.text)]
        context = " ".join(other.text for other in [unit, *related])
        if not (CLOSED.search(context) or AUTHORITY.search(context) and REPAIR.search(context)):
            continue
        check = RepairClosureCheck("insufficient", "closure_status_date_or_permission_unverified", context)
        if (not observed_actions or unit.blocked or any(other.blocked for other in related) or UNCERTAIN.search(context)
                or INCOMPLETE.search(context) or NEGATED_OR_OUTSIDE.search(unit.text) or PENALTY.search(context)
                or OTHER_LOCATION.search(context) or len(locations(context, NUMBERED_STALL)) > 1):
            continue
        if any((REFERENCE.search(other.text) or AUTHORITY.search(other.text) or AUTHORIZATION_TOPIC.search(other.text))
               and (other.blocked or INCOMPLETE.search(other.text) or REOPENED.search(other.text))
               for other in units[index + 1:index + 3]):
            continue
        # A general repair rule cannot establish that the observed stall is closed.
        notices = [other.text for other in related if AUTHORITY.search(other.text) and CLOSED.search(other.text)]
        if len(notices) > 1 or not (
                CLOSED.search(unit.text) or notices and (USE_LINK.search(unit.text)
                or locations(unit.text, NUMBERED_STALL) & locations(notices[0], NUMBERED_STALL))):
            continue
        notice = notices[0] if notices else unit.text
        check = compare_closure(unit.text, notice, context, observed_actions, banned_actions(context))
        if check.state == "supported":
            return check
    return check


def with_repair_closure(description, baseline_codes, normalize):
    check = assess_repair_closure(description, normalize)
    findings = set(baseline_codes)
    if check and check.state == "supported":
        findings.add(CATEGORY)
    return findings, check
