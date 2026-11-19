"""Extract documented liquor-sale facts and compare them with applicable policy."""

from dataclasses import dataclass
from datetime import time
import json
from pathlib import Path
import re

from .incidents import incident_spans
from .pilot_evidence import eligible_incident


LIQUOR = r"\b(?:alcohol|liquor|beer|gin|rum|wine|brandy|alak)\b"
SALE = re.compile(r"\b(?:sold|rang up|nagbenta|naibenta|ibinenta|binenta|ni ring up|na ring up)\b")
NEGATED_SALE = re.compile(
    r"\b(?:no (?:sale|sales)|(?:did not|not|hindi|di) (?:actually )?(?:sell|sold|nagbenta|naibenta)|"
    r"only offered|refused (?:the sale|to sell)|tumangging magbenta|cancelled|voided|refunded|returned|"
    r"non alcoholic|alcohol free|zero alcohol|(?:will|would|could|can) be sold)\b"
)
AGE_LIMIT = re.compile(
    r"\b(?:bawal|may not|must not|prohibit\w*)\b[^.;/]{0,55}" + LIQUOR
    + r"[^.;/]{0,45}\b(?:under|below|wala pang|mas bata sa)\s+(\d{1,2})\b"
    r"|" + LIQUOR + r"\s+(?:may not|must not)\b[^.;/]{0,65}\b(?:under|below)\s+(\d{1,2})\b"
)
AGE = re.compile(r"\b(?:age\s+(\d{1,2})|(\d{1,2})\s+(?:year[s]? old|taong gulang|anyos))\b")
IDENTITY = re.compile(r"\b(?:id|identification|identity card)\b")
SELLER_ID = re.compile(r"\b(?:seller|vendor|stallholder)\s+s\s+id\b|\bid ng (?:seller|vendor|tindero)\b")
BUYER_ROLE = re.compile(r"\b(?:to|sa|buyer|mamimili|whose)\b")
TIME_ROLE = re.compile(r"\b(?:at|nang|ng)\s*$")
OTHER_TIMED_EVENT = re.compile(r"\b(?:opened|closed|arrived|started|inspected|dumating|nagbukas|nagsara)\b")
TIME = r"\b(\d{1,2})(?:\s+([0-5]\d))?\s*(am|pm)\b"
SALE_WINDOW = re.compile(
    r"\b(?:only|lamang|lang)\b[^.;/]{0,75}\b(?:from|mula)\s+"
    + TIME + r"\s+(?:to|until|hanggang)\s+" + TIME
)
CLOCK = re.compile(TIME)

POLICY_FILE = Path(__file__).resolve().parents[1] / "config/liquor_pilot_policy.json"
COMPLETED_SALE = re.compile(
    SALE.pattern
    + r"|\b(?:purchased|bought)\b"
    + r"|\b(?:complet(?:ed|ing)|observed|recorded)\b.{0,28}\b(?:liquor |alcohol )?(?:sale|transaction)\b"
    + r"|\b(?:liquor |alcohol )?(?:sale|transaction)\s+(?:was |is )?(?:recorded|verified|confirmed)\b"
)
UNVERIFIED_SALE = re.compile(
    r"\b(?:whether|unable to confirm|could not verify|did not verify|did not provide|"
    r"(?:customer|buyer|shopper)\s+(?:said|claimed|stated|reported)|reportedly)\b"
)
AGE_CONFIRMATION = re.compile(
    r"^(?:the )?(?:buyer|customer)(?: s)? age\s+(?:was |is )?(?:confirmed|verified)\b"
)
TRANSACTION_TIME = re.compile(r"^(?:the )?(?:same )?(?:transaction|sale)\s+(?:occurred|took place|was recorded)\b")
AGE_SUBJECT = re.compile(r"^(?:the )?(?:buyer|customer)(?: s)? age\b")
TIME_SUBJECT = re.compile(r"^(?:the )?(?:(?:sale|transaction) time|time of (?:the )?(?:sale|transaction))\b")
UNVERIFIED_DETAIL = re.compile(r"\b(?:not (?:confirmed|verified|checked)|unconfirmed|unverified|unclear|unknown)\b")
UNVERIFIED_ID = re.compile(
    r"\b(?:no (?:valid )?(?:id|identification)(?!\s+(?:issues?|problem))|"
    r"(?:id|identification)\s+(?:was |is )?(?:missing|unavailable|not (?:checked|verified|provided)))\b"
)
IDENTIFIED_AGE = re.compile(r"\b(?:age(?: of)?\s+(\d{1,2})|(\d{1,2})\s+(?:years? old|taong gulang|anyos))\b")
CONFIRMED_AGE_VALUE = re.compile(r"\b(?:confirmed|verified)\s+(?:as|at|to be)\s+(\d{1,2})\b")
TIME_PREFIX = re.compile(r"\b(?:at|nang|ng)\s+(?:approximately\s+|about\s+|around\s+)?$")
MARKET_DRINKING_POLICY_ID = "any-person-drinking-inside-market"
DRINKING = r"(?:drank|drinking|sipping|umiinom|uminom|nag inom|nag iinom)"
ALCOHOL_CONSUMPTION = re.compile(r"\b" + DRINKING + r"\b[^,;.!?]{0,35}" + LIQUOR)
NEGATED_DRINKING = re.compile(
    r"\b(?:not|never|no one|nobody|hindi|di|walang)\s+"
    r"(?:(?:was|is|actually|nakitang|naman)\s+)?" + DRINKING + r"\b"
    r"|\b(?:non alcoholic|alcohol free|zero alcohol)\b"
)
DRINKING_UNCERTAIN = re.compile(r"\b(?:baka|daw|raw|posibleng|mukhang|reported(?:ly)?|heard|according to a report)\b")
DRINKING_RULE = re.compile(
    r"^(?:drinking|alcohol consumption)\b.{0,100}\b(?:prohibited|forbidden|not allowed)\b"
)
MARKET_LOCATION = r"(?:(?:the|a|ang)\s+)?(?:(?:city|public)\s+)?(?:market|palengke|pamilihan|merkado)\b"
INSIDE_MARKET = re.compile(
    r"\b(?:inside\s+(?:of\s+)?|in\s+|sa loob ng\s+)" + MARKET_LOCATION
    + r"(?!\s+(?:parking|perimeter|grounds|area|entrance|gate|vicinity|compound)\b)"
)
OUTSIDE_MARKET = re.compile(r"\b(?:outside\s+(?:of\s+)?|not inside\s+|sa labas ng\s+|hindi sa loob ng\s+)" + MARKET_LOCATION)
LOCATION_CHANGE = re.compile(
    r"\b(?:outside|sa labas|then|pagkatapos|lumipat|pumasok|(?:went|walked|moved) inside)\b"
)


@dataclass(frozen=True)
class LiquorPolicy:
    policy_id: str
    minimum_buyer_age: int
    latest_sale_time: int


@dataclass(frozen=True)
class SaleFacts:
    buyer_age: int | None
    sale_time: int | None


def load_pilot_policy(path=POLICY_FILE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    age = data["minimum_buyer_age"]
    cutoff = data["latest_sale_time"]
    if (data["scope"] != "synthetic_evaluation" or type(age) is not int or not 1 <= age <= 99
            or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", cutoff)):
        raise ValueError("Invalid synthetic liquor policy")
    parsed = time.fromisoformat(cutoff)
    return LiquorPolicy(data["policy_id"], age, parsed.hour * 60 + parsed.minute)


def policy_comparisons(description, normalize, policy):
    """Yield comparisons for observed sales under the explicitly selected policy."""
    for facts in observed_sales(description, normalize):
        yield (compare_fact(facts.buyer_age, policy.minimum_buyer_age, below=True), "verified_buyer_age")
        yield (compare_fact(facts.sale_time, policy.latest_sale_time, below=False), "documented_liquor_sale_cutoff")


def market_drinking_comparisons(description, normalize):
    """Apply the working market consumption rule to any observed person."""
    for unit in incident_spans(description, normalize):
        observed = unit.text
        if not ALCOHOL_CONSUMPTION.search(observed) or NEGATED_DRINKING.search(observed):
            continue
        if (not eligible_incident(unit) or DRINKING_RULE.search(observed) or UNVERIFIED_SALE.search(observed)
                or DRINKING_UNCERTAIN.search(observed)):
            state = "insufficient"
        else:
            # Exclude the inside substring in explicit statements such as "not inside".
            inside = INSIDE_MARKET.search(OUTSIDE_MARKET.sub(" ", observed))
            outside = OUTSIDE_MARKET.search(observed)
            if inside and not outside and not LOCATION_CHANGE.search(observed):
                state = "supported"
            elif outside and not inside:
                state = "compliant"
            else:
                state = "insufficient"
        yield state, "observed_drinking_inside_market"


def compare_fact(actual, threshold, *, below):
    if actual is None:
        return "insufficient"
    breached = actual < threshold if below else actual > threshold
    return "supported" if breached else "compliant"


def observed_sales(description, normalize):
    incidents = incident_spans(description, normalize)
    for index, unit in enumerate(incidents):
        observed = unit.text
        sale = COMPLETED_SALE.search(observed)
        if (not sale or not re.search(LIQUOR, observed) or not eligible_incident(unit)
                or NEGATED_SALE.search(observed) or UNVERIFIED_SALE.search(observed)):
            continue
        age_detail, time_detail = sale_details(incidents[index + 1:])
        yield SaleFacts(verified_buyer_age(observed, sale, age_detail),
                        documented_sale_time(observed, sale, time_detail))


def sale_details(followups):
    age_detail = time_detail = ""
    for unit in followups:
        uncertain = (not eligible_incident(unit) or UNVERIFIED_SALE.search(unit.text)
                     or UNVERIFIED_DETAIL.search(unit.text))
        if uncertain and AGE_SUBJECT.search(unit.text):
            age_detail = None
        elif uncertain and TIME_SUBJECT.search(unit.text):
            time_detail = None
        elif not uncertain and AGE_CONFIRMATION.search(unit.text) and age_detail == "":
            age_detail = unit.text
        elif not uncertain and TRANSACTION_TIME.search(unit.text) and time_detail == "":
            time_detail = unit.text
        else:
            break
    return age_detail, time_detail


def verified_buyer_age(observed, sale, detail):
    if detail is None or SELLER_ID.search(observed) or UNVERIFIED_ID.search(observed):
        return None
    ages = list(IDENTIFIED_AGE.finditer(observed, sale.end()))
    if len(ages) > 1:
        return None
    followup_age = CONFIRMED_AGE_VALUE.search(detail)
    has_buyer_id = bool(IDENTITY.search(detail) and not UNVERIFIED_ID.search(detail))
    if not ages:
        return int(followup_age[1]) if followup_age and has_buyer_id else None
    age = ages[0]
    buyer = observed[sale.end():age.start()]
    if not BUYER_ROLE.search(buyer):
        return None
    age_context = observed[max(sale.end(), age.start() - 60):age.end() + 70]
    if not (IDENTITY.search(age_context) or has_buyer_id):
        return None
    age_value = int(age[1] or age[2])
    return None if followup_age and int(followup_age[1]) != age_value else age_value


def documented_sale_time(observed, sale, detail):
    if detail is None:
        return None
    values = list(CLOCK.finditer(observed))
    followup_times = list(CLOCK.finditer(detail))
    if len(values) + len(followup_times) != 1:
        return None
    if followup_times:
        match = followup_times[0]
        return clock_minutes(match.groups()) if TIME_PREFIX.search(detail[:match.start()]) else None
    match = values[0]
    prefix = observed[:match.start()]
    connector = TIME_PREFIX.search(prefix)
    if not connector:
        return None
    if match.start() < sale.start():
        if prefix[:connector.start()].strip() or OTHER_TIMED_EVENT.search(observed[match.end():sale.start()]):
            return None
    elif OTHER_TIMED_EVENT.search(observed[sale.end():match.start()]):
        return None
    if abs(match.start() - sale.end()) > 100:
        return None
    return clock_minutes(match.groups())


def sale_limits(incident):
    """Replay the historical, incident-stated restrictions diagnostic."""
    if not eligible_incident(incident):
        return
    observed, context = incident.text, incident.context
    if not (SALE.search(observed) and re.search(LIQUOR, observed)) or NEGATED_SALE.search(observed):
        return
    age_limits = list(AGE_LIMIT.finditer(context))
    if len(age_limits) == 1:
        yield age_state(observed, age_limits[0]), "verified_buyer_age"
    windows = [window for window in SALE_WINDOW.finditer(context)
               if re.search(LIQUOR, context[max(0, window.start() - 45):window.end()])]
    if len(windows) == 1:
        yield window_state(observed, windows[0]), "documented_liquor_sale_window"


def age_state(observed, limit):
    actual = limit.re.sub(" ", observed)
    sale = SALE.search(actual)
    if not sale or SELLER_ID.search(actual):
        return "insufficient"
    ages = list(AGE.finditer(actual, sale.end()))
    if len(ages) != 1:
        return "insufficient"
    age = ages[0]
    if (not BUYER_ROLE.search(actual[sale.end():age.start()])
            or not IDENTITY.search(actual[max(sale.end(), age.start() - 45):age.end() + 60])):
        return "insufficient"
    threshold = int(limit[1] or limit[2])
    years = int(age[1] or age[2])
    return "supported" if years < threshold else "compliant"


def window_state(observed, window):
    actual = window.re.sub(" ", observed)
    times = list(CLOCK.finditer(actual))
    sale = SALE.search(actual)
    if len(times) != 1 or not sale:
        return "insufficient"
    time = times[0]
    between = actual[min(sale.end(), time.end()):max(sale.start(), time.start())]
    clock_prefix = actual[:time.start()]
    if (len(between) > 90 or OTHER_TIMED_EVENT.search(between)
            or not TIME_ROLE.search(clock_prefix)
            or (time.start() < sale.start() and clock_prefix.strip() != "at")):
        return "insufficient"
    start = clock_minutes(window.groups()[:3])
    end = clock_minutes(window.groups()[3:])
    when = clock_minutes(time.groups())
    if None in (start, end, when) or start == end:
        return "insufficient"
    within = start <= when <= end if start < end else when >= start or when <= end
    return "compliant" if within else "supported"


def clock_minutes(groups):
    hour, minute, suffix = groups
    value = int(hour)
    if not 1 <= value <= 12:
        return None
    return value % 12 * 60 + int(minute or 0) + (720 if suffix == "pm" else 0)
