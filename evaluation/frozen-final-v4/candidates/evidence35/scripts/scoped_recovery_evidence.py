"""Additional offline proofs for a few directly observed incident structures."""
from decimal import Decimal
import re

from src.incidents import UNCERTAIN
from src.reweigh import description_evidence_issue


def found(pattern, text):
    return bool(re.search(pattern, text))


EXIT = r'(?:fire exit|emergency exit|exit door|pinto ng (?:fire exit|labasan))'
OBSTRUCTION = (
    r'\b(?:stack\w*|lined up|placed|isinalansan|inihanay|hinanay)\b.{0,115}'
    r'\b(?:crates?|boxes|bags|sacks?|drums?|kahon|sako)\b.{0,75}'
    r'\b(?:directly in front of|in front of|across|in the path of|sa harap ng) (?:the )?' + EXIT
)
ACTOR = r'\b(?:vendor|seller|stallholder|tindero|tindera|may puwesto)\b'
SHARED_FIXTURE = r'\bshared (?:light|fixture|lamp)\b'
ACTIVE_ORDER = r'\b(?:suspended pa|still suspended|suspension remains in force|closure order remains in force)\b'
SALES = r'\b(?:continued (?:selling|trading)|still selling|sold|nagbenta|nagbebenta|tumanggap.{0,25}orders?|nag abot.{0,25}goods)\b'
RETAIL_LENGTH = re.compile(
    r'\b(?:sold|binenta|cut|pinutol)\b.{0,60}\bas (\d+(?:\.\d+)?) (m|meters?|metres?|cm|centimeters?|centimetres?)\s*[,;]?\s*'
    r'(?:measured|only|just)?\s*(\d+(?:\.\d+)?) (m|meters?|metres?|cm|centimeters?|centimetres?)\b'
)


def length_shortfall(observation):
    if (description_evidence_issue(observation)
            or found(r'\b(?:did not|never|not sold|hindi|di|customer claimed|ayon sa bumili)\b', observation)
            or not found(r'\b(?:measured|checked|inunroll|inspector|inspektor|tinaya|sinukat)\b', observation)):
        return False
    matches = list(RETAIL_LENGTH.finditer(observation))
    if len(matches) != 1:
        return False
    match, = matches
    if not found(r'\b(?:measured|only|just)\b', match[0]) and not found(r'^\s*(?:lang|only)\b', observation[match.end():]):
        return False
    promised, pu, actual, au = match.groups()
    promised_cm = Decimal(promised) * (1 if pu.startswith('c') else 100)
    actual_cm = Decimal(actual) * (1 if au.startswith('c') else 100)
    return 0 < actual_cm < promised_cm


def additional_proofs(unit):
    if unit.blocked or unit.is_requirement or '?' in unit.context or UNCERTAIN.search(unit.context):
        return
    observation, context = unit.text, unit.context
    if found(r'\b(?:no violation|walang paglabag|cleared before|alleged|ayon sa reklamo)\b', context):
        return
    if (found(ACTOR, observation) and found(OBSTRUCTION, observation)
            and not found(r'\b(?:did not|never|hindi|di|walang nakaharang|clear|unobstructed|removed|inalis)\b', observation)):
        yield 'Obstruction'
    if (found(SHARED_FIXTURE, observation) and found(SHARED_FIXTURE, context)
            and found(r'\b(?:patay|pundido|sirang|burnt out|broken|failed|di napalitan|not replaced)\b', observation)
            and found(r'\b(?:row agreement|kasunduan|kontrata|contract)\b', context)
            and found(r'\b(?:must|dapat|kailangang|required)\b.{0,40}\b(?:maintain|keep|panatilihin)\b.{0,45}\bshared (?:light|fixture|lamp)\b', context)
            and found(r'\b(?:this stallholder|stallholder na ito|this vendor|tinderong ito)\b', context)
            and not found(r'\b(?:no fault|working now|gumagana na|napalitan na|fixed|repaired)\b', observation)):
        yield 'Lighting Facilities'
    if (found(ACTOR, observation) and found(ACTIVE_ORDER, observation) and found(SALES, observation)
            and not found(r'\b(?:lifted|expired|ended|no longer|not in force|did not|never|hindi|di|planned|balak)\b', observation)):
        yield 'General Penalties'
    if not unit.weight_blocked and length_shortfall(observation):
        yield 'WeightMeasures'
