"""Verify a vendor ID's observed placement against its stated display duty."""

import re

from .incidents import UNCERTAIN, incident_spans
from .vendor_id_stall import (
    ACTIVE_SELLER, CATEGORY, CURRENT_SITE, DISPLAY_DUTY, ID, ID_MENTION, LINKED_CARD,
    OWN_CARD, SELLING_SITE, SITE_SELLING, StallIDCheck, VENDOR_ID, locations,
)


DISPLAY_WORD = (
    r"(?:display\w*|post\w*|hang\w*|hung|mount\w*|stuck|taped|clipped|"
    r"nakadispley|naka\s*display|nakapaskil|ipaskil|nakasabit|nakadikit|naka\s*(?:clip|tape))"
)
DUTY = re.compile(r"\b(?:must|required|dapat|kailangan(?:g)?|shall)\b")
DISPLAY = re.compile(rf"\b{DISPLAY_WORD}\b")
EYE_LEVEL = r"(?:eye\s*level|kapantay ng mata|pantay sa mata|tapat ng mata)"
EYE = re.compile(rf"\b{EYE_LEVEL}\b")
FRONT = re.compile(
    r"\b(?:stall front|front (?:of (?:the )?(?:stall|counter)|counter)|harap (?:ng|sa) (?:stall|puwesto|pwesto|counter))\b"
)
VISIBLE = re.compile(r"\b(?:visible|readable|legible|mababasa|nabasa|kita|malinaw)\b")
OFF_EYE = re.compile(
    rf"\b(?:above|below|higher than|lower than|lampas sa|mas mataas (?:sa|kaysa sa)|"
    rf"mas mababa (?:sa|kaysa sa))\s+(?:the\s+)?{EYE_LEVEL}\b"
    r"|\b(?:near the floor|below the counter|under the counter|malapit sa sahig|ilalim ng counter)\b"
)
OBSCURED = (
    r"(?:hidden|covered|blocked|obscured|folded|blurred|illegible|unreadable|"
    r"natatakpan|natakpan|nakatakip|nakakubli|nakatago|nakatupi|malabo)"
)
CARD_PART = rf"(?:{ID}|\b(?:name|photo|pangalan|litrato)(?: and photo)?\b)"
CARD_OBSCURED = re.compile(
    rf"{CARD_PART}\s+(?:(?:was|is|partly|partially|niya)\s+)*{OBSCURED}\b"
    rf"|\b{OBSCURED}\s+(?:(?:ang|yung|the|vendor)\s+)*{CARD_PART}"
)
PLACED_CARD = re.compile(
    rf"{ID}\s+(?:(?:was|is|still|niya)\s+)*\b{DISPLAY_WORD}\b"
    rf"|\b{DISPLAY_WORD}\s+(?:(?:ang|yung|the|vendor)\s+)*{ID}"
)
CART = re.compile(
    r"\b(?:left|still|on|in|posted|hung|naiwan|nasa|nakapaskil)\b.{0,32}?"
    r"\b(?:cart|kariton)\b.{0,30}?\b(?:parking(?: area| lot)?|paradahan|off site|away from the stall)\b"
)
OTHER_ITEM = re.compile(
    r"(?:[,;]|\b(?:but|and|while|pero|habang|at)\b)\s+"
    r"(?:(?:the|ang|yung|a)\s+)?(?:price tag|price board|sign|menu|poster|permit|banner|tarpaulin)\b"
)
NON_VENDOR_CARD = re.compile(r"\b(?:porter|kargador|employee|staff|customer|buyer|mamimili)\s+id\b")
UNCLEAR = re.compile(
    r"\b(?:daw|raw|baka|mukhang|reportedly|alleged|claimed|maybe|not sure|couldn t (?:tell|check)|"
    r"can t (?:tell|check)|di (?:pa )?(?:sigurado|sure|alam|nakita|na check|ma check)|"
    r"hindi (?:sigurado|alam|nakita|nakumpirma)|unclear|unknown|"
    r"can t verify|couldn t verify|not verified|kung (?:kita|nasa|nakapaskil|gaano))\b"
)
CORRECTED = re.compile(
    r"\b(?:now (?:displayed|posted|visible)|moved (?:it |the id )?(?:back |down )?(?:to|at)|"
    r"repositioned|corrected|inilipat na|ibinalik na|inayos na|kita na)\b"
)
RULE_EXCEPTION = re.compile(r"\b(?:if|unless|except|optional|proposed|old rule|previous rule|maliban)\b")
CARD_REFERENCE = re.compile(r"^(?:it|this|that|ito|iyon)\b")
NEGATED = re.compile(
    r"\b(?:not|never|no longer|hindi|di)\s+(?:\w+\s+){0,2}"
    r"(?:selling|trading|nagtitinda|nagbebenta|above|below|left|covered|hidden|posted|displayed|naiwan|natatakpan)\b"
)
NOT_VISIBLE = re.compile(r"\b(?:not|never|di|hindi|walang)\s+(?:clearly\s+)?(?:visible|readable|kita|mababasa)\b")


def uncertain(unit):
    return unit.blocked or UNCERTAIN.search(unit.text) or UNCLEAR.search(unit.text)


def display_rule(unit):
    text = unit.text
    if ID_MENTION.search(text) and not RULE_EXCEPTION.search(text) and (duty := DUTY.search(text)):
        governed = text[duty.start():]
        if DISPLAY.search(governed):
            return governed
    return None


def card_clause(text):
    """Keep the placement observation attached to the ID, not an adjacent item."""
    mention = ID_MENTION.search(text)
    tail = OTHER_ITEM.split(text[mention.start():], maxsplit=1)[0]
    head = re.split(r"[,;]|\b(?:and|but|pero|however|habang|while)\b", text[:mention.start()])[-1]
    return head[-42:] + tail


def assess_vendor_id_display(description, normalize):
    units = incident_spans(description, normalize)
    check = None
    for index, unit in enumerate(units):
        text = unit.text
        if unit.is_requirement or not ID_MENTION.search(text) or NON_VENDOR_CARD.search(text):
            continue
        neighbors = [u for i, u in enumerate(units) if abs(index - i) == 1]
        active = text if ACTIVE_SELLER.search(text) else ""
        if not active and LINKED_CARD.search(text) and index:
            prior = units[index - 1]
            if (not prior.is_requirement and not uncertain(prior) and not NEGATED.search(prior.text)
                    and not ID_MENTION.search(prior.text) and ACTIVE_SELLER.search(prior.text)):
                active = prior.text
        if not (active or VENDOR_ID.search(text) or OWN_CARD.search(text)):
            continue
        check = StallIDCheck("insufficient", "vendor_id_placement_or_visibility_unverified", text)
        if not active or uncertain(unit) or NEGATED.search(text) or CORRECTED.search(text):
            continue
        if any((ID_MENTION.search(other.text) or CARD_REFERENCE.search(other.text))
               and (uncertain(other) or CORRECTED.search(other.text))
               for other in neighbors):
            continue
        observed = card_clause(text)
        rules = [rule for other in [unit, *neighbors]
                 if not uncertain(other) and (rule := display_rule(other))]
        for rule in rules:
            evidence = f"{active} {text} {rule}" if active != text else f"{text} {rule}"
            if EYE.search(rule) and PLACED_CARD.search(observed) and OFF_EYE.search(observed):
                return StallIDCheck("supported", "id_placed_outside_required_eye_level", evidence)
            if (DISPLAY_DUTY.search(rule) and CART.search(observed)
                    and (CURRENT_SITE.search(active) or locations(active, SELLING_SITE, SITE_SELLING))
                    and (OWN_CARD.search(text) or re.search(r"\b(?:seller s|vendor s|cart niya|kariton niya)\b", observed))):
                return StallIDCheck("supported", "id_left_on_cart_away_from_trading_stall", evidence)
            if VISIBLE.search(rule) and CARD_OBSCURED.search(observed):
                return StallIDCheck("supported", "id_visibility_requirement_breached", evidence)
        if (PLACED_CARD.search(observed) and FRONT.search(observed) and EYE.search(observed)
                and VISIBLE.search(observed) and not (OFF_EYE.search(observed)
                or CARD_OBSCURED.search(observed) or NOT_VISIBLE.search(observed))):
            check = StallIDCheck("compliant", "id_visible_at_stall_front_and_eye_level", observed)
    return check


def with_vendor_id_display(description, baseline_codes, normalize):
    check = assess_vendor_id_display(description, normalize)
    findings = set(baseline_codes)
    if check and check.state == "supported":
        findings.add(CATEGORY)
    return findings, check
