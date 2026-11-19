"""Description spans with local qualifications and conservative context inheritance."""
from dataclasses import dataclass
import re
from .reweigh import description_evidence_issue


BOUNDARY = re.compile(
    r"\s+/\s+|(?<!\w)\(\d+\)\s*|[;]\s*(?:also\s+)?|"
    r",\s*(?:also|tapos)\s+|\s+tapos\s+|(?<=[.!?])\s+|"
    r"\b(?:separately|in addition|bukod dito|hiwalay rito|dagdag pa)\s*[,;:]\s*", re.I)
ABBREVIATION = re.compile(r"(?:\b(?i:st|sec|no|dr|mr|mrs)|\b[A-Z])\.$")
UNCERTAIN = re.compile(
    r"\b(?:unclear|uncertain|unconfirmed|unverified|alleged\w*|suspect\w*|possibly|maybe|"
    r"might|could have|may have|may be(?!\s+\w+(?:\s+\w+){0,3}\s+only\b)|tsismis|rumou?r|hearsay|anonymous complaint|"
    r"not (?:established|verified|confirmed|checked)|no (?:evidence|details)|"
    r"no (?:record|ledger|measurement|test) (?:has been |was )?checked|ledger not checked|"
    r"(?:maintenance )?duty unknown|responsibility unknown|source stall not identified|"
    r"hindi (?:malinaw|tiyak|kumpirmado)|di (?:malinaw|tiyak)|"
    r"(?:hindi|di) (?:na )?verify|(?:hindi|di) na check|hindi alam|"
    r"baka\s+(?:madaya|kulang|may|hindi|tampered|short)|posible|pakicheck|pakisuri|"
    r"please (?:check|verify)|a tip says|ayon sa tip|asked whether|nagtanong\b.{0,45}\bkung)\b", re.I)
QUALIFIER = re.compile(
    r"^(?:(?:it|this|that|the (?:report|claim|incident))\s+(?:was|is|has been)\s+"
    r"(?:not (?:verified|confirmed|observed)|unconfirmed|unclear)|"
    r"neither\b.{0,65}\b(?:confirmed|verified|observed)|"
    r"(?:neither|both|these|those|all)\b.{0,65}\b(?:unconfirmed|not confirmed|not verified)|"
    r"no (?:record|ledger) (?:has been|was) checked|(?:di|hindi) na check ang (?:ledger|record))", re.I)
GLOBAL_QUALIFIER = re.compile(r"^(?:neither|both|these|those|all)\b", re.I)
REQUIREMENT_START = re.compile(
    r"^(?:(?:rule|patakaran|requirement|req)\b|(?:all )?(?:stallholders?|vendors?) "
    r"(?:must|shall|should)|display goods must|(?:dapat|kailangang)\b)", re.I)
REFERENCE_START = re.compile(r"^(?:it|this|that|they|their|its|siya|ito|ang mga ito)\b", re.I)
QUANTITY = re.compile(r"\b\d+(?:\.\d+)?\s*(?:kg|kilo|grams?|g|ml|liters?|litro|l|cm|m)\b", re.I)
QUANTITY_CONTINUATION = re.compile(r"\b(?:reweigh\w*|timbangan bayan|measured|net weight|verified scale|reference scale)\b", re.I)
CLEAR = re.compile(r"^(?:no violations? (?:found|observed)|walang nakitang paglabag|walang violation|no infraction)[.! ]*$", re.I)
NORMATIVE = re.compile(r"\b(?:must|shall|required|prohibited|bawal|kailangang|dapat|only|lamang|hanggang|rule|patakaran)\b", re.I)
OBSERVED = re.compile(r"\b(?:left|used|built|installed|sold|charged|found|saw|observed|confirmed|"
                      r"parked|in use|drawer|expired|uncovered|dead|broken|flickering|"
                      r"walang|no|missing|without|patay|sirang|nag\w+|naka\w+|ini\w+|isina\w+|mayroon|nakita)\b", re.I)


def requirement_only(text):
    marker = re.search(r"\b(?:rule|req|requirement|patakaran|kailangan|ayon sa kasunduan)\b", text, re.I)
    if marker and marker.start() < 60 and not OBSERVED.search(text[:marker.start()]):
        text = text[marker.start():]
    return bool(REQUIREMENT_START.search(text) or re.search(
        r"^(?:only\b|bawal\b|hanggang\b|at most\b|sa\b.{0,45}\blamang\b|"
        r"(?:nakapaskil na|nakasaad sa|ayon sa)\s+patakaran\b|posted requirement\b|"
        r"under (?:the )?(?:posted )?rule\b|the posted rule\b|"
        r"under (?:the )?row agreement\b|the market service road\b.{0,40}\bonly\b|"
        r"ayon sa kasunduan\b|kailangan\b|"
        r"one way\b.{0,30}\b(?:pahilaga|northbound|only|lamang)\b|"
        r"no (?:one|person|vendor)\b.{0,40}\b(?:may|shall)\b|"
        r"the vendors approved event allowed\b|"
        r"(?:the |each |all |ang |bawat )?[^,;.]{0,65}\b(?:must|shall|should|is required|are required)\b)",
        text, re.I) or re.search(r"\b(?:may (?:not|only)|may\b.{0,30}\b(?:only|at most)|puwede\b.{0,60}\blamang)\b", text, re.I)
        and not OBSERVED.search(text.split(' may ')[0]) or re.search(r"^stalls may draw water\b", text, re.I))


@dataclass(frozen=True)
class Incident:
    text: str
    context: str
    blocked: bool
    reason: str = ""
    weight_blocked: bool = False
    is_requirement: bool = False


def incident_spans(description, normalize):
    """Retain contiguous source context; never split decimals or street initials."""
    boundaries = []
    for match in BOUNDARY.finditer(description):
        if match.start() and description[match.start()-1] == ".":
            abbreviation = ABBREVIATION.search(description[:match.start()])
            if abbreviation and (len(abbreviation[0]) > 2 or re.match(r"[A-Z]\w+\s+St\.", description[match.end():])):
                continue
        boundaries.append(match.span())
    starts = [0, *(end for _, end in boundaries)]
    ends = [*(start for start, _ in boundaries), len(description)]
    raw = [(start, end, normalize(description[start:end]).strip()) for start, end in zip(starts, ends)]
    raw = [item for item in raw if item[2]]
    blocked = {}
    for i, (_, _, text) in enumerate(raw):
        if "?" in text or UNCERTAIN.search(text):
            blocked[i] = "uncertain_incident"
        if QUALIFIER.search(text):
            for previous in (range(i) if GLOBAL_QUALIFIER.search(text) else [i-1]):
                if previous >= 0:
                    blocked[previous] = "unconfirmed_followup"
            blocked[i] = "qualifier_only"
        if CLEAR.fullmatch(text):
            for previous in range(i+1):
                blocked[previous] = "explicit_clear_followup"
    result = []
    for i, (start, end, text) in enumerate(raw):
        context_start = start
        context_end = end
        if i and i-1 not in blocked:
            previous = raw[i-1]
            if (requirement_only(previous[2]) or REFERENCE_START.search(text)
                    or (len(QUANTITY.findall(previous[2])) == 1 and len(QUANTITY.findall(text)) == 1
                        and QUANTITY_CONTINUATION.search(text))):
                context_start = previous[0]
        if i+1 < len(raw) and i+1 not in blocked and requirement_only(raw[i+1][2]):
            context_end = raw[i+1][1]
        weight_blocked = bool(i+1 < len(raw) and description_evidence_issue(raw[i+1][2]))
        result.append(Incident(text, normalize(description[context_start:context_end]), i in blocked,
                               blocked.get(i, ""), weight_blocked, requirement_only(text)))
    return result


def inference_inputs(description, normalize):
    """One stable, deduplicated batch shared by production and evaluation."""
    values = [normalize(description)]
    values.extend(unit.context for unit in incident_spans(description, normalize) if not unit.blocked)
    return list(dict.fromkeys(values))
