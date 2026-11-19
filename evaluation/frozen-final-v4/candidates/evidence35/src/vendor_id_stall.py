"""Check the location of a displayed vendor ID without changing v4 scores."""

from dataclasses import dataclass
import re

from .incidents import UNCERTAIN, incident_spans


CATEGORY = "Vendor Identification"
LOCATION = r"(?:stall|store|shop|booth|pwesto|puwesto|tindahan|st\.)"
SITE = rf"\b{LOCATION}\s+(?:(?:no|number)\.?\s+)?([a-z]?\s*\d{{1,5}}[a-z]?)\b"
ID = r"\b(?:id(?: card)?|identification card)\b"
ID_MENTION = re.compile(ID)
VENDOR_ID = re.compile(r"\b(?:vendor|seller|stallholder|assigned) " + ID)
SELL = r"\b(?:selling|trading|sells|nagtitinda|nagbebenta)\b"
ACTIVE_SELLER = re.compile(SELL)
PREPOSITION = r"(?:at|in|from|on|outside|sa)(?: a| an| the)?"
SELLING_SITE = re.compile(rf"{SELL}(?:(?!{ID}).){{0,35}}?\b{PREPOSITION}\s+{SITE}")
SITE_SELLING = re.compile(rf"^(?:{PREPOSITION}\s+)?{SITE}[ ,.]*(?:(?!{ID}).){{0,50}}?{SELL}")
CURRENT_SITE = re.compile(
    rf"{SELL}\s+(?:(?:ang|si)\s+(?:tindero|tindera|seller|vendor)\s+)?"
    r"(?:at this (?:stall|store)|here|dito|sa (?:stall na ito|puwestong ito|pwestong ito))\b"
)
DISPLAY = (
    r"\b(?:displayed|posted|hung|clipped|taped|naka\s*display|naka\s*post|"
    r"nakadispley|nakapaskil|nakasabit|nakadikit)\b"
)
DISPLAYED_CARD = (
    rf"(?:{ID}(?:\s+(?:is|was|still|remains|stayed|niya))*\s+{DISPLAY}|"
    rf"{DISPLAY}\s+(?:(?:pa rin|ang|yung|yong|the|vendor|assigned)\s+)*{ID}(?:\s+niya)?)"
)
DISPLAY_SITE = re.compile(
    rf"{DISPLAYED_CARD}\s+(?:pa rin\s+)?{PREPOSITION}\s+{SITE}"
)
DISPLAY_BEFORE_CARD = re.compile(
    rf"{DISPLAY}\s+{PREPOSITION}\s+{SITE}\s+(?:(?:ang|yung|the|vendor|assigned)\s+)*{ID}"
)
VISIBLE_ID = re.compile(
    rf"(?:{ID}.{{0,25}}?{DISPLAY}|{DISPLAY}.{{0,25}}?{ID})"
)
ASSIGNMENT = (
    rf"{ID}(?:\s+(?:was|is|still|na|ay|niya))*\s+"
    r"(?:(?:assigned|issued|registered)\s+(?:to|for|sa)|"
    r"belongs to|lists|shows|names|says|for|para sa|nakatalaga sa|nakalista sa|ng)\s+"
)
REFERENCED_CARD = (
    r"\b(?:it|that card|same (?:vendor )?id|ito|iyon)\s+(?:(?:was|is|ay)\s+)?"
    r"(?:(?:assigned|issued|registered)\s+(?:to|for|sa)|belongs to|para sa)\s+"
)
ASSIGNED_SITE = re.compile(rf"{ASSIGNMENT}(?:the\s+)?{SITE}")
REFERENCED_ASSIGNMENT = re.compile(rf"{REFERENCED_CARD}(?:the\s+)?{SITE}")
ASSIGNED_THEN_DISPLAYED = re.compile(
    rf"{ASSIGNED_SITE.pattern}[ ,]+(?:(?:is|was|still|and|ay)\s+)*{DISPLAY}\s+{PREPOSITION}\s+{SITE}"
)
DISPLAYED_THEN_ASSIGNED = re.compile(
    rf"{DISPLAY_SITE.pattern}[ ,]+(?:but|and)\s+(?:(?:is|was|still)\s+)*"
    rf"(?:assigned|issued|registered)\s+(?:to|for|sa)\s+{SITE}"
)
OTHER_SITE = rf"(?:(?:a|the)\s+)?(?:different|other|another|ibang)\s+{LOCATION}\b"
OTHER_ASSIGNMENT = re.compile(rf"{ASSIGNMENT}{OTHER_SITE}")
OTHER_REFERENCE = re.compile(rf"{REFERENCED_CARD}{OTHER_SITE}")
REVERSED_OTHER = re.compile(rf"\bpara sa {OTHER_SITE}\s+(?:ang|yung)\s+(?:vendor\s+)?(?:{ID}|card\b)")
ON_CARD = re.compile(rf"{SITE}\s+ang\s+(?:nakalagay|nakasulat|nakalista)\s+sa\s+(?:vendor\s+)?{ID}")
ASSIGNMENT_LIST = re.compile(
    rf"(?:{ASSIGNED_SITE.pattern}|{REFERENCED_ASSIGNMENT.pattern})"
    rf"(?:\s+(?:and|or|at|o)\s+|,\s*)(?:{LOCATION}\s+)?[a-z]?\s*\d+"
)
DISPLAY_OTHER = re.compile(
    rf"(?:{ID}.{{0,25}}?{DISPLAY}|{DISPLAY}.{{0,25}}?{ID})"
    rf".{{0,24}}?\b{PREPOSITION}\s+(?:(?:seller s|vendor s|tindero s)\s+)?(?:"
    rf"(?:neighboring|neighbouring|former|previous|second|different|other|katabing|dating|ikalawang|ibang)\s+{LOCATION}(?:ng)?|"
    rf"{LOCATION}\s+(?:next door|next to (?:it|this one)))\b"
)
DISPLAY_DUTY = re.compile(
    r"\b(?:must|required|dapat|kailangang|kailangan)\b.{0,100}"
    r"\b(?:display\w*|posted|nakadispley|naka\s*display|nakapaskil|ipaskil)\b.{0,120}"
    r"\b(?:currently (?:selling|trading)|(?:now|actually) (?:selling|trading)|"
    r"(?:selling|trading) (?:now|today)|kasalukuyang (?:nagtitinda|pinagtitindahan)|"
    r"kung saan (?:nagbebenta|nagtitinda)|stall where (?:they|the seller|the vendor) (?:trade|sell))\b"
)
OWN_CARD = re.compile(
    rf"\b(?:his|her|their|own|assigned)\s+(?:vendor\s+)?{ID}|"
    rf"{ID}\s+(?:niya|ng tindero|ng tindera|ng seller|ng vendor)\b"
)
LINKED_CARD = re.compile(
    rf"^(?:his|her|their|the seller s|the vendor s)\s+(?:vendor\s+)?{ID}|"
    rf"^(?:yung |ang )?(?:vendor\s+)?{ID}\s+niya\b"
)
UNCLEAR = re.compile(
    r"\b(?:daw|raw|baka|mukhang|rumou?r|reportedly|claimed|unreadable|can t (?:read|verify|tell)|"
    r"couldn t (?:read|verify|tell)|di (?:pa )?(?:mabasa|nabas[ae]|sigurado|sure|"
    r"nakumpirma|ma verify|ma check|alam)|hindi (?:mabasa|nabasa|sigurado|alam)|"
    r"not (?:sure|known|checked|verified)|unknown|unclear|unverified)\b"
)
EXCLUDED = re.compile(
    r"\b(?:porter|kargador|customer|buyer|mamimili|employee|staff)\s+(?:vendor\s+)?id\b|"
    r"\b(?:both|multiple|shared)\s+(?:stores?|stalls?|puwesto)|"
    r"\b(?:second|spare|duplicate|another|other|ibang)\s+(?:vendor\s+)?id\b|"
    r"\b(?:approved|authorized|temporary|pending)\s+(?:transfer|relocation)|"
    r"\b(?:transfer|relocation)\s+(?:was\s+)?(?:approved|authorized|pending)|"
    r"\b(?:never|not|no longer|hindi|di|walang)\s+(?:\w+\s+){0,2}"
    rf"(?:{SELL}|{DISPLAY})"
)
OTHER_DOCUMENT = re.compile(r"\b(?:permit|license|certificate)\b")


@dataclass(frozen=True)
class StallIDCheck:
    state: str
    reason: str
    evidence: str


def locations(text, *patterns):
    return {match[1].replace(" ", "") for pattern in patterns for match in pattern.finditer(text)}


def unreliable(unit):
    return (unit.blocked or UNCERTAIN.search(unit.text) or UNCLEAR.search(unit.text)
            or EXCLUDED.search(unit.text) or ASSIGNMENT_LIST.search(unit.text))


def assess_vendor_id_stall(description, normalize):
    """Compare actual display/trading and assignment within a linked observation."""
    units = incident_spans(description, normalize)
    check = None
    for index, unit in enumerate(units):
        text = unit.text
        if unit.is_requirement or not ID_MENTION.search(text):
            continue
        if not (VENDOR_ID.search(text) or OWN_CARD.search(text) or
                VISIBLE_ID.search(text) and ACTIVE_SELLER.search(text)):
            continue
        check = StallIDCheck("insufficient", "vendor_id_stall_match_unverified", text)
        if unreliable(unit):
            continue
        neighbors = [u for i, u in enumerate(units) if abs(index - i) == 1]
        if any(unreliable(u) and ID_MENTION.search(u.text) for u in neighbors):
            continue
        observed = text
        trading = locations(text, SELLING_SITE, SITE_SELLING)
        if not trading and LINKED_CARD.search(text) and index:
            previous = units[index - 1]
            if not (previous.is_requirement or unreliable(previous) or ID_MENTION.search(previous.text)):
                trading = locations(previous.text, SELLING_SITE, SITE_SELLING)
                if trading:
                    observed = f"{previous.text} {text}"
        display = locations(text, DISPLAY_SITE, DISPLAY_BEFORE_CARD)
        assigned = locations(text, ASSIGNED_SITE, ON_CARD)
        for recorded, posted in ASSIGNED_THEN_DISPLAYED.findall(text):
            assigned.add(recorded.replace(" ", ""))
            display.add(posted.replace(" ", ""))
        for posted, recorded in DISPLAYED_THEN_ASSIGNED.findall(text):
            display.add(posted.replace(" ", ""))
            assigned.add(recorded.replace(" ", ""))
        only_card = not OTHER_DOCUMENT.search(text)
        if only_card:
            assigned |= locations(text, REFERENCED_ASSIGNMENT)
        if len(trading) > 1 or len(display) > 1 or len(assigned) > 1:
            continue
        # A stall-assigned vendor card displayed at a numbered stall is direct evidence.
        if display and assigned and (VENDOR_ID.search(text) or trading):
            if display != assigned:
                return StallIDCheck("supported", "displayed_id_assigned_to_different_stall", observed)
            if not trading or trading == display:
                check = StallIDCheck("compliant", "vendor_id_matches_display_stall", observed)
                continue
        if (VISIBLE_ID.search(text) and (VENDOR_ID.search(text) or trading)
                and (OTHER_ASSIGNMENT.search(text) or REVERSED_OTHER.search(text)
                     or only_card and OTHER_REFERENCE.search(text))):
            return StallIDCheck("supported", "displayed_id_assigned_to_different_stall", observed)
        # A relative location needs the same seller, current stall, and a stated display duty.
        duty = next((item.text for item in [unit, *neighbors]
                     if not unreliable(item) and DISPLAY_DUTY.search(item.text)), None)
        if duty and (trading or CURRENT_SITE.search(text)) and (
                OWN_CARD.search(text) or re.search(rf"\b(?:while|habang)\b.{{0,40}}{ID}", text)):
            if DISPLAY_OTHER.search(text) or trading and display and trading != display:
                return StallIDCheck("supported", "seller_id_displayed_away_from_trading_stall", f"{observed} {duty}")
            if display and display == trading and (not assigned or assigned == trading):
                check = StallIDCheck("compliant", "seller_id_displayed_at_trading_stall", observed)
                continue
        # A display stated as 'here' may use the linked, numbered trading stall.
        if trading and assigned and OWN_CARD.search(text) and re.search(
                rf"{DISPLAY}\s+(?:here|dito|at this stall|sa stall na ito)\b", text):
            if trading != assigned:
                return StallIDCheck("supported", "displayed_id_assigned_to_different_stall", observed)
            check = StallIDCheck("compliant", "vendor_id_matches_display_stall", observed)
    return check


def with_vendor_id_stall(description, baseline_codes, normalize):
    check = assess_vendor_id_stall(description, normalize)
    findings = set(baseline_codes)
    if check and check.state == "supported":
        findings.add(CATEGORY)
    return findings, check
