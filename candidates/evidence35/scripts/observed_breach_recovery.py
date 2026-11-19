"""Conservative offline recovery for explicitly stated facts and comparisons."""
from decimal import Decimal
import re

from scripts.scoped_recovery_evidence import ACTOR, found
from src.incidents import UNCERTAIN
from src.reweigh import description_evidence_issue


CONDITIONAL = r'\b(?:if|kung|hypothetical|example only|planned|plan to|balak|suppose|reported by a customer|ayon sa reklamo)\b'
CORRECTED = r'\b(?:later corrected|was corrected|resolved before|rectified|subsequently paid|has since|naayos na|itinama na|binayaran na)\b'
NEGATION = r'\b(?:did not|never|was not|were not|walang paglabag|no violation|hindi|di)\b'
TIME = r'(\d{1,2})(?:\s+([0-5]\d))?'
TAP = r'\b(?:common|shared|communal) (?:water )?tap\b|\b(?:gripo ng palengke|komunal na gripo)\b'
STALL = r'\b(?:stall|puwesto|pwesto)\b'
SERVICE_ROAD = r'\b(?:service road|service lane|daang serbisyo)\b'
ROAD_ACTOR = ACTOR + r'|\b(?:helper|katulong|stall delivery driver)\b'
CONSTRUCTION = r'\b(?:built|constructed|installed|itinayo|ipinakabit|ipinagawa|pinatayo|nagpatayo|nagkabit)\b'
STRUCTURE = r'\b(?:floor|sahig|stairs?|hagdan|loft|storage|imbakan|extension|partition|canopy|cabinet|kabinet|pader|wall|shelf)\b'
NO_BUILDING_APPROVAL = (
    r'\b(?:without(?: a| the)?|walang|nang walang) (?:construction |building |alteration )?(?:permit|approval|pahintulot)\b.{0,55}'
    r'\b(?:market admin\w*|administrator ng palengke|building office)\b'
    r'|\b(?:only|lamang|lang)\b.{0,60}\b(?:pending|nakabinbing)\b.{0,25}\b(?:approval|permit|aplikasyon|application)\b'
    r'|\b(?:pending|nakabinbing)\b.{0,25}\b(?:approval|permit|aplikasyon|application)\b.{0,45}\b(?:only|lamang|lang)\b'
)


def opposite_direction(observation, context):
    one_way = r'\b(?:one way|oneway|iisa ang direksyon)\b'
    if not found(SERVICE_ROAD, observation) or not found(
            SERVICE_ROAD + r'[^.;]{0,48}' + one_way + '|' + one_way + r'[^.;]{0,48}' + SERVICE_ROAD, context):
        return False
    if not found(r'\b(?:drove|reversed|rode|driving|nagdrive|nag drive|nagmaneho|minaneho|inatras|bumiyahe)\b', observation):
        return False
    directions = (r'(?:northbound|north|pahilaga|hilaga)', r'(?:southbound|south|patimog|timog|pa timog)',
                  r'(?:eastbound|east|pasilangan|silangan)', r'(?:westbound|west|pakanluran|kanluran)')
    for required, contrary in zip(directions, (directions[1], directions[0], directions[3], directions[2])):
        if found(r'\b(?:only|lamang)\b.{0,20}\b' + required + r'\b|\b' + required + r'\b.{0,20}\b(?:only|lamang)\b', context):
            return found(r'\b' + contrary + r'\b|\b(?:wrong way|maling direksyon)\b', observation)
    return False


def to_minutes(hour, minute, suffix):
    hour = int(hour)
    if not 1 <= hour <= 12:
        return None
    return hour % 12 * 60 + int(minute or 0) + (720 if suffix == 'pm' else 0)


def outside_water_allocation(observation, context):
    if (not found(TAP, observation) or not found(r'\b(?:draw\w*|fill\w*|pinupuno|pinuno|sumalok|kumukuha|kumuha)\b', observation)
            or not found(r'\b(?:only|lang|lamang)\b', context) or not found(r'\b(?:allocation|alokasyon)\b', context)):
        return False
    window = re.search(r'\b' + TIME + r'\s+(?:to\s+)?' + TIME + r'\s*(am|pm)\s+(?:allocation|alokasyon)\b', context)
    actual = list(re.finditer(r'\b' + TIME + r'\s*(am|pm)\b', observation))
    if not window or not found(TAP, context[max(0, window.start()-95):window.end()+95]):
        return False
    start = to_minutes(window[1], window[2], window[5])
    end = to_minutes(window[3], window[4], window[5])
    if len(actual) == 1:
        observed = to_minutes(*actual[0].groups())
    elif not actual and found(r'\b(?:noon|tanghali)\b', observation):
        observed = 720
    else:
        return False
    return None not in (start, end, observed) and start < end and not start <= observed <= end


def over_vehicle_limit(observation, context):
    if (not found(r'\baccess road\b', observation) or not found(r'\baccess road\b', context)
            or not found(r'\b(?:vehicle|truck|lorry|tanker|trailer|sasakyan)\b', observation)
            or not found(r'\b(?:used|drove|parked|entered|ginamit|ipinarada|dumaan|pumasok)\b', observation)
            or not found(r'\b(?:bawal|prohibited|may not|not allowed)\b', context)):
        return False
    units = r'(tons?|tonnes?|tonelada(?:ng)?)\b'
    quantity = r'(\d+(?:\.\d+)?)\s*' + units
    limit = re.search(r'\b(?:over|lampas|more than)\s+' + quantity, context)
    actual = re.findall(r'\b' + quantity, observation)
    if not limit or len(actual) != 1:
        return False
    value, unit = actual[0]
    return unit.rstrip('s').removesuffix('ng') == limit[2].rstrip('s').removesuffix('ng') and Decimal(value) > Decimal(limit[1])


def verified_scale_alteration(observation):
    if description_evidence_issue(observation) or not found(r'\b(?:scale|timbangan|beam balance)\b', observation):
        return False
    return found(r'\b(?:hollowed out|hinollow out|binutas)\b.{0,35}\b(?:counterweight|panimbang)\b'
                 r'|\b(?:counterweight|panimbang)\b.{0,35}\b(?:hollowed out|hinollow out|binutas)\b'
                 r'|\b(?:filed down|kinikil|kinayod)\b.{0,50}\b(?:internal |panloob na )?lever\b'
                 r'|\b(?:replaced|pinalitan)\b.{0,75}\b(?:non standard|hindi pamantayang|weaker|mas mahina)\b.{0,30}\bspring\b', observation)


def grounded_codes(unit):
    if (unit.blocked or unit.is_requirement or '?' in unit.context or UNCERTAIN.search(unit.context)
            or found(CONDITIONAL, unit.context) or found(CORRECTED, unit.context)):
        return
    observed, context = unit.text, unit.context
    if found(ACTOR, observed) and not found(NEGATION, observed):
        if (found(CONSTRUCTION, observed) and found(STRUCTURE, observed) and found(NO_BUILDING_APPROVAL, observed)
                and not found(r'\b(?:permit in force|valid permit|approved plan|approved by)\b', observed)):
            yield 'Stall Construction'
        if (found(STALL, observed) and found(r'\b(?:used|using|ginagamit)\b', observed)
                and found(r'\b(?:parking|paradahan|rest area|pahingahan|imbakan ng construction materials|storing construction materials)\b', observed)
                and found(r'\b(?:only for (?:selling|sales)|for (?:selling|sales) only|para sa pagtitinda lamang|pagtitinda lang)\b', context)):
            yield 'Stall Occupancy'
        if (found(r'\b(?:caused|nagdulot|umani)\b', observed)
                and found(r'\b(?:crowd|crowding|siksikan|pagdagsa|nagtutulakang kumpol)\b', observed)
                and found(r'\b(?:stopped selling|sales stopped|tumigil ang bentahan|huminto ang bentahan|nagsara ang mga kalapit|nearby stalls closed|natumba ang mga display)\b', observed)):
            yield 'Public Order'
        if (found(r'\b(?:was smoking|smoked a cigarette|nagyoyosi|naninigarilyo|nagsigarilyo)\b', observed)
                and found(r'\b(?:smoking is not allowed|no smoking|bawal manigarilyo|prohibits smoking)\b', context)
                and found(r'\b(?:at stall|sa stall|inside|loob|market building|gusali ng palengke)\b', observed)):
            yield 'Market Rules'
    if found(ROAD_ACTOR, observed) and not found(NEGATION, observed):
        if opposite_direction(observed, context) or over_vehicle_limit(observed, context):
            yield 'Traffic'
        if outside_water_allocation(observed, context):
            yield 'Utilities'
    scale_observation = re.sub(r'\bhindi pamantayang\b', 'non standard', observed)
    if not unit.weight_blocked and not found(NEGATION, scale_observation) and verified_scale_alteration(scale_observation):
        yield 'WeightMeasures'
