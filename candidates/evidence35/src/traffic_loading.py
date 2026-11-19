"""Check observed delivery locations and engine use against local traffic rules."""

from dataclasses import dataclass
import re

from .incidents import UNCERTAIN, incident_spans


CATEGORY = "Traffic"
VEHICLE = re.compile(r"\b(?:trucks?|trak|vans?|pick\s*ups?|tricycles?|sasakyan|vehicles?|delivery lorr(?:y|ies))\b")
OBSERVED_UNLOAD = r"(?:unloaded|unloading|nag\s*unload|nagbaba|nagbababa|nagdiskarga)"
OBSERVED_LOAD = r"(?:loaded|loading|nag\s*load|nagkarga|nagkakarga)"
UNLOAD = rf"(?:{OBSERVED_UNLOAD}|unload|mag\s*unload|ibaba|magbaba|pagbaba)"
LOAD = rf"(?:{OBSERVED_LOAD}|load|mag\s*load|ikarga|magkarga|pagkarga)"
LOAD_ACTION = re.compile(
    rf"\b(?:(?P<unload>{UNLOAD})|(?P<load>{LOAD}))\b"
    r"(?!\s+(?:bay|zone|lane|area|ramp|limit|restriction|rule)\b)"
)
OBSERVED_LOADING = re.compile(
    rf"\b(?:(?P<unload>{OBSERVED_UNLOAD})|(?P<load>{OBSERVED_LOAD}))\b"
    r"(?!\s+(?:bay|zone|lane|area|ramp|limit|restriction|rule)\b)"
)
ENGINE_ON = re.compile(
    r"\b(?:engine[s]? (?:was |were |is |are |still )?(?:running|on)|"
    r"(?:kept|left) (?:its |the )?engine[s]? running|naka\s*on (?:yung |ang )?(?:engine|makina)|"
    r"(?:tumatakbo|umaandar|bukas) ang makina|idled|idling|naka\s*idle|pinaandar)\b"
)
ENGINE_OFF = re.compile(
    r"\b(?:engine[s]? (?:was |were |is |are )?(?:off|switched off|turned off)|"
    r"(?:switched|turned) off (?:the |its )?engine[s]?|naka\s*off (?:yung |ang )?(?:engine|makina)|"
    r"(?:patay|pinatay) ang makina)\b"
)
WAITING = re.compile(
    r"\b(?:waiting|waited|idled|idling|naka\s*idle|naghihintay|naghintay|nag\s*antay|nag\s*aantay)\b"
)
ZONE_WORDS = {
    "curb": r"(?:(?:street|corner|roadside) )?curb|roadside|side of (?:the )?road|gilid ng kalsada|tabi ng kalsada",
    "bike_lane": r"bike lane|bicycle lane",
    "fire_lane": r"fire lane|fire access lane",
    "pedestrian_lane": r"pedestrian (?:lane|walkway)|sidewalk|bangketa",
    "bay": r"(?:(?:designated|approved|marked|authorized|allowed|itinakdang|tamang)\s+)?(?:loading |unloading )?bay|"
           r"(?:(?:designated|approved|marked|authorized|allowed|itinakdang|tamang)\s+)?(?:loading|unloading) zone",
    "parking": r"parking (?:area|lot|lane)",
}
NUMBERED_BAY = re.compile(r"\b(?:loading |unloading )?bay\s+([a-z]?\s*\d{1,4}[a-z]?)\b")
OUTSIDE_BAY = re.compile(r"\b(?:outside|labas ng|lampas sa) (?:the )?(?:designated |marked |itinakdang )?loading bay\b")
APPROVED_BAY = re.compile(
    r"\b(?:designated|approved|authorized|allowed|marked|itinakdang|tamang) (?:loading|unloading) (?:bay|zone)\b"
)
ZONE_PATTERNS = {kind: re.compile(rf"\b(?:{pattern})\b") for kind, pattern in ZONE_WORDS.items()}
ACTUAL_ZONE = re.compile(
    r"\b(?:at|in|on|inside|sa) (?:the |a |an |loob ng )?(?P<site>"
    + "|".join(rf"(?:{pattern})" for pattern in ZONE_WORDS.values()) + r")\b"
)
LOADING_BAN = re.compile(
    rf"\b(?:no|bawal|prohibited|not allowed to)\s+(?P<actions>(?:{UNLOAD}|{LOAD})"
    rf"(?:\s+(?:(?:and|or|at|o)\s+)?(?:{UNLOAD}|{LOAD}))?)\b"
    r"(?!\s+(?:bay|restriction|rule|ban)\b)"
)
BAY_PLACE = rf"(?:{ZONE_WORDS['bay']}|(?:loading |unloading )?bay\s+[a-z]?\s*\d+)"
REQUIRED_BAY = re.compile(
    rf"\b(?:must|shall|required to|dapat|kailangan(?:g)?)\s+(?:be\s+|i\s+)?(?:{UNLOAD}|{LOAD})\b"
    rf"[^,.;]{{0,38}}?\b(?:at|in|inside|sa) (?:the )?(?:{BAY_PLACE})\b"
    rf"|\b(?:dapat|kailangan(?:g)?)\s+sa (?:{BAY_PLACE})\b[^,.;]{{0,28}}?\b(?:{UNLOAD}|{LOAD})\b"
    rf"|\b(?:{UNLOAD}|{LOAD})\s+(?:is\s+)?(?:allowed\s+)?only\s+(?:at|in|inside) (?:the )?(?:{BAY_PLACE})\b"
)
ENGINE_DUTY = re.compile(
    r"\b(?:must (?:switch|turn|shut) off.{0,24}engines?|"
    r"engines? must be (?:off|switched off|turned off)|engine[s]? off (?:required|only)|"
    r"no idling|bawal mag\s*idle|(?:kailangang|dapat) patayin ang makina|"
    r"dapat naka\s*off (?:ang |yung )?(?:engine|makina))\b"
)
PERMITTED_ENGINE = re.compile(
    r"\b(?:with (?:written |official )?(?:permission|clearance|approval) to keep (?:its |the )?engine on|"
    r"approved to keep (?:its |the )?engine on|may pahintulot na (?:panatilihing )?naka\s*on ang makina|"
    r"pinayagang (?:panatilihing )?naka\s*on ang (?:engine|makina)|"
    r"(?:this|the) (?:truck|van) (?:was |is )?(?:authorized|allowed|permitted) to idle)\b"
)
EXCEPTION = re.compile(
    r"\b(?:except|unless|maliban|exempt\w*|with prior permission|clearance (?:is )?required|"
    r"(?:over|more than|longer than|lampas sa) \d+\s*(?:mins?|minutes?|minuto)|"
    r"(?:from|after|before|between) \d{1,2}(?:\s*:\s*\d{2})?\s*(?:am|pm)|"
    r"(?:during|outside) (?:market |delivery |loading )?hours)\b"
)
NO_PERMISSION = re.compile(r"\b(?:without (?:written )?(?:permission|clearance)|no clearance|walang (?:pahintulot|clearance))\b")
UNCLEAR = re.compile(
    r"\b(?:daw|raw|baka|mukhang|reportedly|alleged|claimed|maybe|not sure|unknown|unclear|"
    r"couldn t (?:see|check|tell|read)|can t (?:see|check|tell|read)|not verified|"
    r"di (?:sure|sigurado|alam|mabasa|nakita|na check)|hindi (?:tiyak|alam|mabasa)|"
    r"unreadable|faded sign|covered sign|sign covered|sign missing|signage missing|sign not visible|"
    r"not (?:in force|in effect|applicable)|no longer (?:applies|required)|old sign|expired sign)\b"
)
ENGINE_NEGATED = re.compile(r"\b(?:not|never|di|hindi)\s+(?:(?:was|is|naka)\s+)?(?:idling|idle|running|switched off|turned off)\b")
ENGINE_TRANSITION = re.compile(r"\b(?:(?:then|later) (?:switched|turned|shut) off|engine now off)\b")
UNREALIZED = re.compile(
    r"\b(?:did not (?:unload|load|idle)|didn t (?:unload|load|idle)|"
    r"(?:di|hindi) (?:nag\s*unload|nag\s*load|nagbaba|nagkarga|naka\s*idle)|"
    r"planned to|about to|told to|waiting to (?:unload|load)|before (?:unloading|loading)|"
    r"loaded with|will (?:unload|load)|stopped before)\b"
)
REFERENCE = re.compile(r"^(?:(?:it|this|that|ito|iyon)\b|(?:the |ang )?(?:sign|signage|location|engine status)\b)")
INLINE_RULE = re.compile(
    r",\s*(?:(?:posted )?(?:rule|sign|requirement)\b|no (?:loading|unloading|idling)\b|"
    r"bawal\b|(?:dapat|kailangang)\b|(?:vehicles?|engines?|deliveries) must\b)"
)


@dataclass(frozen=True)
class TrafficRuleCheck:
    state: str
    reason: str
    evidence: str


def zones(text):
    if OUTSIDE_BAY.search(text):
        return {"outside_bay"}
    numbered = {f"bay:{match[1].replace(' ', '')}" for match in NUMBERED_BAY.finditer(text)}
    found = {kind for kind, pattern in ZONE_PATTERNS.items() if pattern.search(text)}
    if numbered:
        found.discard("bay")
    return found | numbered


def observed_zone(text):
    if OUTSIDE_BAY.search(text):
        return "outside_bay"
    sites = set()
    for match in ACTUAL_ZONE.finditer(text):
        # The bay number is immediately after the matched location phrase.
        sites.update(zones(text[match.start("site"):match.end() + 6]))
    return sites.pop() if len(sites) == 1 else None


def applies(site, scope):
    return site in scope or (site.startswith("bay:") and "bay" in scope)


def loading_result(observed, site, operations, rules):
    allowed_bay = APPROVED_BAY.search(observed) and (site == "bay" or site.startswith("bay:"))
    compliant = bool(allowed_bay)
    for rule in rules:
        evidence = f"{observed} {rule}"
        scope = zones(rule)
        for ban in LOADING_BAN.finditer(rule):
            prohibited = {m.lastgroup for m in LOAD_ACTION.finditer(ban["actions"])}
            ban_scope = zones(rule[ban.end():].split(",", 1)[0]) or zones(rule[:ban.start()])
            if applies(site, ban_scope) and operations & prohibited:
                if allowed_bay or EXCEPTION.search(rule) and not NO_PERMISSION.search(evidence):
                    return None
                return TrafficRuleCheck("supported", "loading_in_prohibited_location", evidence)
        required = {m.lastgroup for m in LOAD_ACTION.finditer(rule)}
        bays = {place for place in scope if place == "bay" or place.startswith("bay:")}
        if (len(bays) != 1 or not REQUIRED_BAY.search(rule) or not operations & required
                or EXCEPTION.search(rule) and not NO_PERMISSION.search(evidence)):
            continue
        if applies(site, bays):
            compliant = True
        elif site != "bay" and not allowed_bay:
            return TrafficRuleCheck("supported", "loading_outside_required_bay", evidence)
    if compliant:
        return TrafficRuleCheck("compliant", "loading_at_allowed_location", observed)
    return None


def engine_result(observed, site, rules):
    if not WAITING.search(observed) or ENGINE_NEGATED.search(observed) or ENGINE_TRANSITION.search(observed):
        return None
    status = PERMITTED_ENGINE.sub("", observed)
    engine_on, engine_off = ENGINE_ON.search(status), ENGINE_OFF.search(status)
    if bool(engine_on) == bool(engine_off):
        return None
    if engine_on and PERMITTED_ENGINE.search(observed) and not NO_PERMISSION.search(observed):
        return TrafficRuleCheck("compliant", "observed_engine_use_explicitly_permitted", observed)
    for text in rules:
        if not any(ENGINE_DUTY.search(part) and applies(site, zones(part)) for part in text.split(",")):
            continue
        evidence = f"{observed} {text}"
        if engine_off:
            return TrafficRuleCheck("compliant", "engine_off_while_waiting", evidence)
        if not EXCEPTION.search(text) or NO_PERMISSION.search(evidence):
            return TrafficRuleCheck("supported", "engine_running_in_engine_off_zone", evidence)
    return None


def uncertain(text):
    return UNCERTAIN.search(text) or UNCLEAR.search(text)


def assess_traffic_loading(description, normalize):
    units = incident_spans(description, normalize)
    check = None
    for index, unit in enumerate(units):
        if unit.is_requirement or not VEHICLE.search(unit.text):
            continue
        inline = INLINE_RULE.search(unit.text)
        observed = unit.text[:inline.start()] if inline else unit.text
        operations = ({match.lastgroup for match in OBSERVED_LOADING.finditer(observed)}
                      if not UNREALIZED.search(observed) else set())
        if not (operations or WAITING.search(observed) or ENGINE_ON.search(observed) or ENGINE_OFF.search(observed)):
            continue
        check = TrafficRuleCheck("insufficient", "loading_location_rule_or_engine_status_unverified", observed)
        if unit.blocked or uncertain(unit.text):
            continue
        site = observed_zone(observed)
        if not site:
            continue
        neighbors = units[max(0, index - 1):index] + units[index + 1:index + 2]
        if any((REFERENCE.search(other.text) or ENGINE_DUTY.search(other.text) or LOADING_BAN.search(other.text))
               and (other.blocked or uncertain(other.text)) for other in [*neighbors, *units[index + 2:index + 3]]):
            continue
        rules = [other.text for other in neighbors if not other.blocked and not uncertain(other.text)]
        if inline:
            rules.append(unit.text[inline.start() + 1:])
        results = [result for result in (loading_result(observed, site, operations, rules) if operations else None,
                                        engine_result(observed, site, rules)) if result]
        for result in results:
            if result.state == "supported":
                return result
        if results:
            check = results[0]
    return check


def with_traffic_loading(description, baseline_codes, normalize):
    check = assess_traffic_loading(description, normalize)
    findings = set(baseline_codes)
    if check and check.state == "supported":
        findings.add(CATEGORY)
    return findings, check
