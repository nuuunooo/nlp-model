"""Identify observed alcohol consumption and compare its context with pilot policy."""

import json
from pathlib import Path
import re

from .incidents import incident_spans
from .pilot_evidence import eligible_incident


POLICY_FILE = Path(__file__).resolve().parents[1] / "config/liquor_consumption_pilot_policy.json"
ALCOHOL = r"\b(?:alcohol|liquor|beer|wine|gin|rum|brandy|whisky|whiskey|vodka|alak|lambanog|tuba)\b"
DRINK = (
    r"\b(?:drink(?:s|ing)?|drank|sipp(?:ed|ing)|took\s+(?:(?:a few|several|\d+)\s+)?sips?"
    r"|umiinom|uminom|nag\s*(?:inom|iinuman)|humihigop|humigop|iniinom)\b"
)
CONSUMPTION = re.compile(
    DRINK + r"\s+(?:(?:a|an|some|ng|nito|from|of|sa|the|isang|shot|sip|sips|glass|cup|bottle|can|bote|baso)\s+){0,6}"
    + ALCOHOL + r"|" + ALCOHOL + r"\s+ang\s+(?:iniinom|inumin|ininom)\b"
)
DOUBT = re.compile(
    r"\b(?:daw|raw|mukhang|looked like|appeared to|thought|reported(?:ly)?|"
    r"heard that|claimed|nagreklamo|hinala|plann?ed to|about to)\b"
)
NO_DRINKERS = re.compile(
    r"\b(?:no one|nobody|walang)\b(?:\s+\w+){0,4}\s+" + DRINK
)
NEGATED_DRINKING = re.compile(
    NO_DRINKERS.pattern
    + r"|\b(?:no|hindi|di|not|without)\s+(?:(?:observed|actually|talagang)\s+)?" + DRINK
    + r"|\b(?:alcohol free|non alcoholic|zero alcohol)\b"
)
DENIAL_WITHOUT_DRINK_VERB = re.compile(
    r"\b(?:no|walang)\s+(?:observed |reported )?" + ALCOHOL + r"\s+(?:was\s+)?consum(?:ed|ption)\b"
)
PUBLIC_PLACE = re.compile(
    r"\b(?:public (?:place|space|sidewalk|plaza|park|market)|pampublikong (?:lugar|plaza|daan)|"
    r"publikong lugar|(?:inside|within|at|in) (?:the )?(?:city |public )?market|"
    r"(?:inside|within|at|in) (?:the )?marketplace|market (?:aisle|hall|concourse|entrance)|"
    r"sa (?:loob ng |pasilyo ng )?palengke)\b"
)
PRIVATE_PLACE = re.compile(r"\b(?:at home|in (?:a|the|his|her) private (?:room|home)|sa (?:sarili niyang )?bahay)\b")
MARKET_ENTRY = re.compile(r"\b(?:at (?:the )?entrance|sa (?:may |mismong )?entrance|sa pasukan)\b")
SELLING = (
    r"\b(?:selling|nagtitinda|nagbebenta|nagbebenta pa|taking payments?(?: from customers)?|"
    r"ringing up (?:sales|purchases)|serving customers)\b"
)
WHILE = r"(?:while|habang|as)"
ACTIVE_PREFIX = re.compile(r"^" + WHILE + r"\s+" + SELLING)
ACTIVE_BEFORE_DRINK = re.compile(SELLING + r".{0,45}\b" + WHILE + r"\s*$")
ACTIVE_AFTER_DRINK = re.compile(
    r"\b" + WHILE + r"\s+(?:(?:he|she|siya)\s+(?:was |continued |kept )?)?" + SELLING
)
OTHER_ACTOR = re.compile(
    r"\b(?:ang|si|the|his|her|a)\s+(?:vendor|seller|stallholder|helper|customer|buyer|tindero|tindera|mamimili|katulong)\b"
)


def load_consumption_policy(path=POLICY_FILE):
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    contexts = policy["qualifying_contexts"]
    if (policy["scope"] != "synthetic_evaluation" or not contexts
            or not set(contexts) <= {"public_place", "actively_selling"}):
        raise ValueError("Invalid synthetic liquor consumption policy")
    return policy


def consumption_evidence(description, normalize, policy, *, market_inspection=False):
    for incident in incident_spans(description, normalize):
        observed = incident.text
        if (not eligible_incident(incident) or DOUBT.search(incident.context)
                or NEGATED_DRINKING.search(observed)):
            continue
        for drink in CONSUMPTION.finditer(observed):
            contexts = set()
            in_public = PUBLIC_PLACE.search(observed) or (market_inspection and MARKET_ENTRY.search(observed))
            if in_public and not PRIVATE_PLACE.search(observed):
                contexts.add("public_place")
            if drinking_while_selling(observed, drink):
                contexts.add("actively_selling")
            for context in policy["qualifying_contexts"]:
                if context in contexts:
                    yield context, observed


def drinking_while_selling(text, drink):
    before, after = text[:drink.start()], text[drink.end():]
    if ACTIVE_BEFORE_DRINK.search(before) or ACTIVE_AFTER_DRINK.search(after):
        return True
    selling = ACTIVE_PREFIX.match(before)
    if not selling:
        return False
    # An explicit actor inside the selling clause can differ from the drinker.
    selling_clause = before[selling.end():].split(",", 1)[0]
    return not OTHER_ACTOR.search(selling_clause)


def consumption_safeguard(description, normalize, evidence, *, independent_liquor_evidence=False):
    """Return a veto for a consumption finding without positive scoped evidence."""
    if evidence or independent_liquor_evidence:
        return None
    observed = [unit.text for unit in incident_spans(description, normalize) if not unit.is_requirement]
    if any(DENIAL_WITHOUT_DRINK_VERB.search(text) or NO_DRINKERS.search(text) for text in observed):
        return "negated_consumption"
    mentions = [text for text in observed if CONSUMPTION.search(text)]
    if not mentions:
        return None
    if any(NEGATED_DRINKING.search(text) for text in mentions):
        return "negated_consumption"
    return "insufficient_consumption_evidence"
