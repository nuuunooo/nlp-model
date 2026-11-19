"""Extract recommendation evidence from the inspection description."""

from decimal import Decimal
import re

from .reweigh import WEIGHT_CODE, description_evidence_issue


UNITS = {
    "kg": 1000, "kilo": 1000, "kilos": 1000, "kilogram": 1000, "kilograms": 1000,
    "g": 1, "gram": 1, "grams": 1, "gramo": 1,
    "ml": 1, "milliliter": 1, "milliliters": 1, "millilitre": 1, "millilitres": 1,
    "l": 1000, "liter": 1000, "liters": 1000, "litre": 1000, "litres": 1000, "litro": 1000,
    "m": 100, "meter": 100, "meters": 100, "metre": 100, "metres": 100, "metro": 100,
    "cm": 1, "centimeter": 1, "centimeters": 1,
}
UNIT_DIMENSIONS = {
    **dict.fromkeys(("kg","kilo","kilos","kilogram","kilograms","g","gram","grams","gramo"), "mass"),
    **dict.fromkeys(("ml","milliliter","milliliters","millilitre","millilitres",
                     "l","liter","liters","litre","litres","litro"), "volume"),
    **dict.fromkeys(("m","meter","meters","metre","metres","metro","cm","centimeter","centimeters"), "length"),
}
QUANTITY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(" + "|".join(UNITS) + r")\b", re.I)
DECLARED_BEFORE = re.compile(
    r"\b(?:declared|advertised|sold|bagged|packed|labeled|labelled|requested|paid for|"
    r"binili|binenta|ibinenta|ibinentang|binayaran|bilang|singil|inorder|nakalagay|cut|pinutol|"
    r"receipt for|priced for)\s*(?:as|at|na|bilang)?\s*$", re.I)
DECLARED_AFTER = re.compile(
    r"^\s*(?:of\s+\w+\s+)?(?:declared|sold|requested|paid|binili|ang singil|ang binili|"
    r"ang nasa resibo|on receipt|daw)\b", re.I)
MEASURED_BEFORE = re.compile(
    r"\b(?:measured|reweighed|weighed|actual|tinimbang|pagtimbang|pagtitimbang|"
    r"net(?: weight)?(?: on (?:the )?(?:public|reference|verified) scale)?|"
    r"timbangan bayan(?: reading)?|lumabas|totoong timbang)\s*(?:(?:at|na|only|lang|was)\s*)?$", re.I)
MEASURED_AFTER = re.compile(
    r"^\s*(?:(?:lang|lamang)\s+(?:sa|on)\s+(?:steel tape|measuring tape|timbangan bayan)|"
    r"on (?:the )?(?:reference|public|verified) scale|sa timbangan bayan|measured|actual|"
    r"ang net|ang lumabas|lang ang lumabas|ang tinimbang|ang totoong timbang)\b", re.I)
UNRESOLVED = re.compile(
    r"\b(?:no specific purchase|walang specific|walang tiyak|may have been mixed|"
    r"already (?:used|removed)|melted and drained|hindi na naitimbang|"
    r"walang (?:calibration|resibo)|no receipt|unverified|uncertain|conflicting|"
    r"pakicheck|paki check|pakisuri|please check|suspected|maybe|posible)\b"
    r"|\bbaka\s+(?:madaya|kulang|may|hindi|tampered|short)\b|\?", re.I)
SCALE_FAULT = re.compile(
    r"\b(?:tampered|rigged|madaya(?:ng)?|dinaya|manipulated|unregistered|uncalibrated|"
    r"walang seal|walang registration|hindi rehistrado|may daya)\b"
    r"|\b(?:magnet|lead weight|metal washer|tingga)\b.{0,65}\b(?:hidden|taped|nakatago|nakadikit)\b"
    r"|\b(?:hidden|taped|nakatago|nakadikit)\b.{0,65}\b(?:magnet|lead weight|metal washer|tingga)\b"
    r"|\b(?:dial|sticker|counterweight|spring|lever)\b.{0,70}\b(?:shifted|swapped|weaker|hollowed|filed down)\b"
    r"|\b(?:inilipat|ginalaw|pinahina|kinayod|binawasan|binutasan)\b.{0,70}\b(?:dial|sticker|spring|lever|counterweight)\b", re.I)
SCALE = re.compile(r"\b(?:scale|scales|timbangang?|panukat|seal wire|platform|pinggan|beam balance)\b", re.I)
SCALE_VERIFICATION_FAULT = re.compile(
    r"\b(?:verification register|register)\b.{0,100}\b(?:rejected|condemned|failed|bumagsak|tinanggihan)\b"
    r"|\b(?:rejected|condemned|failed|bumagsak|tinanggihan)\b.{0,100}\b(?:verification register|re verification|sealing|beripikasyon)\b"
    r"|\b(?:never submitted|never sinubmit|hindi kailanman isinumite)\s+(?:for|para sa)\s+sealing\b", re.I)
SCALE_SEAL_FAULT = re.compile(
    r"\b(?:sealing wire|seal wire|lead seal|seal|selyo)\b.{0,95}\b(?:cut|missing|crushed|reattached with tape|"
    r"nawawala|durog|hindi mabasa|di mabasa)\b"
    r"|\b(?:pinutol|nawawala|durog|hindi mabasa|di mabasa)\b.{0,45}\b(?:sealing wire|seal wire|lead seal|selyo|seal)\b"
    r"|\bseal tag\b.{0,55}\b(?:different|ibang)\s+(?:scale|timbangan)\b", re.I)
SEAL_ACCIDENT = re.compile(r"\b(?:accident\w*|accidentally|fell|dropped|nabagsak|nahulog)\b", re.I)
NEGATED_FAULT = re.compile(
    r"\b(?:not|no|hindi|di|walang)\s+(?:found to be\s+)?"
    r"(?:tampered|rigged|madaya|daya|manipulated|rejected|condemned|missing|cut|tinanggihan)\b", re.I)

# A topic check prevents an unrelated high-scoring label from creating an action.
CATEGORY_TERMS = {
    "Vendor Identification": r"\b(?:id|identification|pagkakakilanlan)\b",
    "Permit & Licensing": r"\b(?:permit|license|licence|lisensya|certificate|sertipiko)\b",
    "Sanitation": r"\b(?:food|pagkain|paninda|dirty|marumi|basura|garbage|pests?|ipis|daga|hygiene|sanitation|contaminat\w*|residue|slimy|murky|dumi|madulas|malagkit|malabong|kaliskis|chiller|thermometer|probe|warmer|temperature|temperatura|ice box|sangkalan)\b",
    "Lighting & Energy": r"\b(?:electric\w*|kuryente|watt|outlet|appliance|lamp|bulb|ilaw|cord)\b",
    "Stall Occupancy": r"\b(?:occup\w*|award\w*|umookupa|dwelling|bakanteng|household|same house|pamilya|sambahayan|parking spot|resting area|private office|pang tinda|para sa pagtitinda|used only for selling|construction materials)\b",
    "Stall Management": r"\b(?:extinguisher|shutter|padlock|logbook|number plate|management|attended|unattended|emergency card|emergency contact|contact card|stall damage|roof leak|broken counter|cracked partition|tagas|sira ng puwesto|iniulat)\b",
    "Stall Construction": r"\b(?:construct\w*|alteration|built|building|weld\w*|counter|partition|renovat\w*|construction|giniba|itinayo|installed|nagpatayo|itinayong|ginawang|ininstall|nagkabit|kinabit|hollow block|pader|canopy|cabinet|cabinets)\b",
    "Utilities": r"\b(?:water|tubig|drain\w*|hose|pipe|faucet|meter|utility|utilities)\b",
    "Stall Rental": r"\b(?:rent\w*|upa|lease|sublet\w*|sublease|goodwill)\b",
    "Illegal Vendor": r"\b(?:unauthorized|vending authorization|no (?:vending permit|assigned space|permit)|walang (?:pahintulot|puwesto|permit|awtorisasyon)|illegal vendor|peddl\w*|parking (?:area|slots)|paradahan|hindi lugar ng pagtitinda)\b",
    "Public Order": r"\b(?:fight\w*|punch\w*|sigawan|shout\w*|disturban\w*|gambl\w*|suntukan|loud|maingay|firecracker\w*|smoke bomb|stampede|crush|pushing crowd|crowd blocked|paputok|takbuhan|nagsiksikan|nagtulakan|nagkagulo|usok)\b",
    "Liquor": r"\b(?:beer|gin|liquor|alcohol|alak|lambanog|tuba|wine|rum)\b",
    "Market Conduct": r"\b(?:insult\w*|curs\w*|threat\w*|harass\w*|grab\w*|change|sukli|minura|pinilit|unwelcome|remarks|body|objection|refused|would not serve|turned away|touched|shoulder|sumipol|katawan|tumanggi|umayaw|hinawakan|tinanggihan|tumangging|numero)\b",
    "Obstruction": r"\b(?:aisle|walkway|passage|pasilyo|daan|exit|entrance|ramp|corridor|blocked|nakaharang)\b",
    "DressCode": r"\b(?:wear\w*|wore|sando|shirt\w*|apron|hairnet|cap|slippers|boots|gloves|kasuotan)\b",
    "Bladed Instruments": r"\b(?:knife|knives|blade|cleaver|bolo|machete|kutsilyo|itak)\b",
    "Traffic": r"\b(?:traffic|truck|van|vehicle|motorcycle|tricycle|parking|parked|loading|unloading|sasakyan)\b",
    "Porter Regulation": r"\b(?:porter|kargador|wheeler)\b",
    "Promotions": r"\b(?:raffle|promo\w*|giveaway|sampling|prize|draw)\b",
    "Advertising": r"\b(?:advert\w*|flyer\w*|leaflet\w*|loudspeaker|brochure|ad|ads|anunsyo)\b",
    "Signage & Streamers": r"\b(?:sign\w*|streamer|banner|tarpaulin|karatula|tarp)\b",
    "Entertainment Activities": r"\b(?:band|perform\w*|show|concert|filming|karaoke|dance|contest|event)\b",
    "Lighting Facilities": r"\b(?:light|lamp|bulb|fixture|ilaw|backlight\w*|backlit)\b",
    "Market Rules": r"\b(?:rule\w*|bawal|must|allowed|closing|schedule|trading hours|smoking|cleaning day)\b",
    "Price Monitoring": r"\b(?:price|presyo|charged|singil|srp|price tag|tagged|tag|unit price|per kilo|kada kilo)\b",
    "Market Fees & Surcharges": r"\b(?:fees?|surcharge|collection|bayarin|buwis)\b",
    "Resisting Authority": r"\b(?:inspector|enforcer|officer|citation|collector|awtoridad)\b",
    "General Penalties": r"\b(?:suspension|suspend\w*|closure|penalt\w*|sarado)\b",
}
CATEGORY_PATTERNS = {code: re.compile(pattern, re.I) for code, pattern in CATEGORY_TERMS.items()}
UNCERTAIN_NOTE = re.compile(
    r"\b(?:unclear|uncertain|unconfirmed|alleged(?:ly)?|suspect\w*|possibly|maybe|"
    r"not (?:established|verified|confirmed)|no (?:test|measurement|evidence)|"
    r"hindi (?:malinaw|tiyak|kumpirmado)|di (?:malinaw|tiyak)|baka|posible|"
    r"pakicheck|pakisuri|please check|a tip says|ayon sa tip|asked whether|nagtanong\b.{0,45}\bkung|"
    r"no (?:record|ledger) (?:has been|was) checked|(?:di|hindi) na check ang (?:ledger|record))\b", re.I)
COMPLIANT_CATEGORY = {
    "Traffic": re.compile(r"\b(?:within (?:the )?allowed window|sa pinapayagang oras|sa tamang oras)\b", re.I),
    "Promotions": re.compile(
        r"\b(?:approval number\b.{0,45}(?:posted|nakapaskil|naka post)|"
        r"(?:nakapaskil|naka post)\b.{0,30}approval number)\b.{0,100}\b(?:public|pampubliko)\b", re.I),
    "Market Fees & Surcharges": re.compile(r"\b(?:full payment|paid in full|buong bayad)\b", re.I),
    "Utilities": re.compile(r"\b(?:drain\b.{0,45}(?:flowed freely|free flowing)|free flowing ang drain|maluwag ang agos ng drain)\b", re.I),
    "Liquor": re.compile(
        r"\b(?:no alcohol was seen|no liquor was (?:seen|found)|walang (?:nakitang )?alak)\b", re.I),
    "Stall Construction": re.compile(
        r"\b(?:matched the approved plan|match sa approved plan|tugma sa aprubadong plano\w*)\b", re.I),
    "DressCode": re.compile(
        r"\b(?:wore the required|suot\b.{0,35}\b(?:required|kinakailangang))\b", re.I),
    "Lighting Facilities": re.compile(
        r"(?<!dapat )(?<!hindi )(?<!di )\bgumagana\s+(?:ang|yung)\b"
        r"|\b(?:light|lamp|fixture)\b.{0,100}\b(?:was working|worked properly)\b", re.I),
}
SPECIFIC_RULE_TOPICS = re.compile(
    r"\b(?:trading hours|closing time|cleaning (?:day|schedule|period)|noon washing|"
    r"delivery (?:gate|entrance)|service gate|smoking|cigarette|pets?|dog|stray|"
    r"cooking|cooked|bata|sigarilyo|manigarilyo|aso|oras ng (?:pagtitinda|pagsasara)|"
    r"oras ng bentahan|araw ng paglilinis|nagluluto|mga bata)\b", re.I)
RAIN_COVER_REQUIREMENT = re.compile(
    r"\b(?:must be covered|(?:kailangang|dapat) takpan)\b.{0,90}\b(?:tarpaulin|tarp)\b", re.I)
WET_GOODS = re.compile(
    r"\b(?:got wet|get soaked|got soaked|drenched|uncovered and wet|"
    r"mabasa|nababasa|basa|basang basa)\b", re.I)
TIME_PARTS = r"(\d{1,2})(?:(?::|\s+)([0-5]\d))?\s*(am|pm)\b"
COLD_ROOM_DEADLINE = re.compile(
    r"\b(?:must remove|(?:kailangang|dapat) alisin)\b.{0,100}"
    r"\b(?:by|before|bago mag)\s+" + TIME_PARTS, re.I)
COLD_ROOM_OBSERVATION = re.compile(
    r"\b(?:still|stayed|left|past|pa rin|naiwan|iniwan|cold room log)\b", re.I)
CLOCK_TIME = re.compile(r"\b" + TIME_PARTS, re.I)
PUBLIC_DISTURBANCE = re.compile(
    r"\b(?:drunk|intoxicated|lasing|in protest|as protest|bilang protesta|"
    r"human chain|kadena ng tao|chanting|nagcha chant|nagsisigaw ng islogan)\b", re.I)
TRADING_DISRUPTION = re.compile(
    r"\b(?:shoppers avoided|shoppers could not reach|aisle emptied|nearby stalls closed|"
    r"could not serve customers|trading\b.{0,30}\bstalled|stopped trading|halting trade|"
    r"iniwasan|natigil ang bentahan|nagsara\b.{0,45}\b(?:puwesto|stalls)|"
    r"nawalan ng tao|naubos ang tao|(?:hindi|di) makapag\w*\s*(?:serve|silbi)|"
    r"(?:hindi|di) makarating|(?:tumigil|huminto) ang bentahan)\b", re.I)
CUSTOMER_ABUSE = re.compile(
    r"\b(?:customer|buyer|mamimili)\b.{0,130}\b(?:cheapskate|kuripot|mock|kutyain|"
    r"do not serve|huwag pagsilbihan)\b"
    r"|\b(?:announced|ipinagsigawan|pinagsigawan)\b.{0,100}\b(?:debt|utang)\b"
    r".{0,100}\b(?:customer|buyer|mamimili)\b"
    r"|\b(?:announced|broadcast|publicized)\b.{0,65}\b(?:customer|buyer)\b.{0,45}\bdebt\b", re.I)
NEIGHBOR_SABOTAGE = re.compile(
    r"\b(?:poured water|unplugged|cut|binuhusan|binunot|pinutol)\b"
    r".{0,110}\b(?:neighboring vendor|neighbouring vendor|katabing (?:tindero|vendor))\b"
    r".{0,75}\b(?:rice sacks|freezer|price cards?|display lights?|sako|kable|cords?)\b"
    r"|\b(?:poured water|unplugged|cut|binuhusan|binunot|pinutol)\b"
    r".{0,100}\b(?:rice sacks|freezer|price cards?|display lights?|sako|kable|cords?)\b"
    r".{0,100}\b(?:neighboring vendor|neighbouring vendor|katabing (?:tindero|vendor))\b"
    r"|\b(?:moved|inilipat|nilipat)\b.{0,130}\b(?:price cards?)\b"
    r".{0,110}\b(?:higher prices|mas mataas na presyo|mas mahal)\b", re.I)
DIRECT_NEGATION = re.compile(
    r"\b(?:not|never|hindi|di)\s+(?:drunk|intoxicated|lasing|unplugged|moved|"
    r"pinutol|binunot|nilipat|cut|in protest|wet|basa)\b", re.I)
VENDOR_ACTOR = re.compile(
    r"\b(?:vendors?|stallholders?|sellers?|helpers?|tindero|tindera|may puwesto|katulong)\b", re.I)
PRIZE_SUBSTITUTION = re.compile(
    r"\b(?:substitut\w*|replaced|pinalit)\b.{0,120}\b(?:prize|premyo)\b", re.I)
INCIDENT_SEPARATOR = re.compile(
    r"\s+/\s+|(?<!\w)\(\d+\)\s+|(?<=[.!?;])\s+|"
    r"\b(?:separately|in addition|bukod dito|hiwalay rito|dagdag pa)\s*[,;:]\s*", re.I)
INCIDENT_RULES = {
    "Obstruction": (
        r"\b(?:stack\w*|strung|left|nagpatong|nag stack|isinabit|iniwan)\b"
        r".{0,80}\b(?:crates?|boxes|kahon|fish|isda)\b.{0,70}\b(?:across|against|sa)\b"
        r".{0,35}\b(?:ramp|rampa|passage|daanan|walkway|pasilyo)\b"
        r".{0,70}\b(?:narrow\w*|blocking|kumitid|(?:hindi|di) makadaan)\b"
        r"|\b(?:left|iniwan)\b.{0,45}\b(?:boxes|crates|kahon)\b"
        r".{0,30}\b(?:on the stairs|sa hagdan|sa hagdanan)\b"
    ),
    "Sanitation": (
        r"\b(?:spat|dumura|sneezed|bumahing)\b.{0,45}\b(?:over|onto|beside|sa tabi ng|sa ibabaw ng)\b.{0,30}"
        r"\b(?:food|pagkain|paninda|food display|lutong pagkain)\b"
        r"|\b(?:open|bukas|nakabukas)\b.{0,30}\b(?:kerosene|gaas)\b"
        r".{0,60}\b(?:above|over|itaas|taas)\b.{0,35}\b(?:vegetables|gulay|food|pagkain)\b"
    ),
    "Stall Management": (
        r"\b(?:had not reported|never reported|failed to report|hindi iniulat|di iniulat|"
        r"hindi naiulat|di ni report|hindi ni report)\b.{0,70}"
        r"\b(?:roof leak|broken counter tile|cracked partition|tagas|bitak)\b"
    ),
    "Permit & Licensing": (
        r"\b(?:meat dealer|lpg retail|business|sanitary|cold storage)\b.{0,25}"
        r"\b(?:license|licence|permit|lisensya)\b.{0,85}"
        r"\b(?:names a different stall|belongs to another owner|sa ibang puwesto|ibang may ari)\b"
    ),
    "Price Monitoring": (
        r"\b(?:displayed no|no|walang|hindi nakapaskil ang|di naka post ang)\b"
        r".{0,26}\b(?:srp card|official price card)\b"
    ),
    "Market Conduct": (
        r"\b(?:refused to sell|would not serve|tinanggihang bentahan|ayaw pagsilbihan)\b"
        r".{0,65}\b(?:religious attire|wheelchair|indigenous|pananamit na panrelihiyon|katutubo)\b"
    ),
    "Utilities": (
        r"\b(?:tied|itinali|tinali)\b.{0,55}\b(?:shared faucet|common tap|gripo)\b"
        r".{0,48}\b(?:open with wire|open|nakabukas)\b"
    ),
    "Resisting Authority": (
        r"\b(?:phoned|called|tinawagan)\b.{0,35}\b(?:inspector|inspektor|enforcer)\b"
        r".{0,48}\b(?:posing as|nagpanggap)\b.{0,55}\b(?:cancel|kanselahin)\b"
    ),
    "Advertising": (
        r"\b(?:leaflets|flyers|ads|paskil)\b.{0,55}"
        r"\b(?:told shoppers to avoid|urged customers to boycott|sinabihan\b.{0,25}\biwasan)\b"
        r"|\b(?:stuck|put|idinikit|dumikit)\b.{0,35}\b(?:ad labels|ad stickers)\b"
        r".{0,45}\b(?:loose bread|unpackaged food|tinapay na walang balot)\b"
    ),
}
INCIDENT_PATTERNS = {code: re.compile(pattern, re.I) for code, pattern in INCIDENT_RULES.items()}
INCIDENT_HEDGE = re.compile(
    r"\b(?:may have|might have|could have|would be|must not|should not|did not|"
    r"didn t|hindi naman|kung sakali|mukhang)\b", re.I)
INCIDENT_QUALIFIER = re.compile(
    r"^(?:it|this|the (?:report|claim|incident))\s+(?:was|is|has been)\s+"
    r"(?:not (?:verified|confirmed|observed)|unconfirmed|unclear)\b", re.I)


def described_incidents(description, normalize):
    """Match concrete observations independently across a ticket's statements."""
    statements = [normalize(part) for part in INCIDENT_SEPARATOR.split(description)]
    for index, text in enumerate(statements):
        if ("?" in text or UNCERTAIN_NOTE.search(text) or INCIDENT_HEDGE.search(text)
                or re.match(r"^(?:rule|patakaran|requirement|req)\b", text)):
            continue
        if followed_by_unconfirmed_statement(statements, index):
            continue
        for code, pattern in INCIDENT_PATTERNS.items():
            if pattern.search(text):
                yield code, text


def followed_by_unconfirmed_statement(statements, index):
    return index + 1 < len(statements) and bool(INCIDENT_QUALIFIER.search(statements[index + 1]))


def described_weight_outcome(text):
    """Return a supported fault, compliant comparison, or insufficient evidence."""
    issue = description_evidence_issue(text)
    if issue or UNRESOLVED.search(text):
        return "unknown", issue or "weight_evidence_unresolved", None
    quantities = [match for match in QUANTITY.finditer(text)
                  if not re.match(r"\s+(?:check|test)\s+weight\b", text[match.end():], re.I)]
    if len(quantities) == 2 and UNIT_DIMENSIONS[quantities[0][2]] == UNIT_DIMENSIONS[quantities[1][2]]:
        first, second = quantities
        before_first = text[max(0, first.start()-60):first.start()]
        between = text[first.end():second.start()]
        after_second = text[second.end():second.end()+65]
        # Direction comes from the note's quantity roles, never numeric size.
        forward = bool(DECLARED_BEFORE.search(before_first) or DECLARED_AFTER.search(between)
                       or MEASURED_BEFORE.search(between) or MEASURED_AFTER.search(after_second))
        reverse = bool(MEASURED_BEFORE.search(before_first)
                       or (MEASURED_AFTER.search(between) and not MEASURED_BEFORE.search(between))
                       or DECLARED_BEFORE.search(between) or DECLARED_AFTER.search(after_second))
        if re.search(r"\b(?:vs|versus|against|for)\b", between):
            reverse = reverse or bool(re.search(r"\b(?:weigh\w*|measured|tinimbang)\b", before_first))
        if forward != reverse and not PRIZE_SUBSTITUTION.search(before_first + first[0] + between + second[0] + after_second):
            values = [Decimal(m[1]) * UNITS[m[2]] for m in quantities]
            declared, measured = values if forward else reversed(values)
            if declared > 0 and measured > 0:
                evidence = text[first.start():second.end()]
                return ("violation" if measured < declared else "compliant"), "", evidence
    if SCALE.search(text) and not NEGATED_FAULT.search(text) and (
        SCALE_FAULT.search(text) or SCALE_VERIFICATION_FAULT.search(text)
        or (SCALE_SEAL_FAULT.search(text) and not SEAL_ACCIDENT.search(text))
    ):
        return "violation", "", text[:200]
    return "unknown", "insufficient_weight_evidence", None


def clock_minutes(match):
    hour = int(match[1])
    if not 1 <= hour <= 12:
        return None
    return (hour % 12 + (12 if match[3].lower() == "pm" else 0)) * 60 + int(match[2] or 0)


def directly_described_categories(text):
    """Recognize documented incidents even when the classifier misses the label."""
    # Keep an uncertain report from confirming another category by itself.
    if UNCERTAIN_NOTE.search(text) or DIRECT_NEGATION.search(text) or "?" in text:
        return
    if RAIN_COVER_REQUIREMENT.search(text) and WET_GOODS.search(text) and re.search(
        r"\b(?:rain\w*|umuulan)\b", text
    ):
        yield "Stall Management"
    elif "cold room" in text and (deadline := COLD_ROOM_DEADLINE.search(text)):
        cutoff = clock_minutes(deadline)
        # Remove the stated requirement so its own timestamp cannot count as an observation.
        start, end = deadline.span()
        observation = text[:start] + " " + text[end:]
        observation_sentences = re.split(r"(?<=[.!?;])\s+", observation)
        times = [
            clock_minutes(match)
            for sentence in observation_sentences
            if "cold room" in sentence and COLD_ROOM_OBSERVATION.search(sentence)
            for match in CLOCK_TIME.finditer(sentence)
        ]
        if cutoff is not None and (
            (cutoff >= 12 * 60 and re.search(
                r"\b(?:left|iniwan)\b.{0,80}\b(?:overnight|magdamag)\b", observation
            ))
            or any(time is not None and time > cutoff for time in times)
        ):
            yield "Stall Management"
    if not VENDOR_ACTOR.search(text):
        return
    if PUBLIC_DISTURBANCE.search(text) and TRADING_DISRUPTION.search(text):
        yield "Public Order"
    if CUSTOMER_ABUSE.search(text) or NEIGHBOR_SABOTAGE.search(text):
        yield "Market Conduct"


def temperature_violation(text):
    """Use an actual temperature and a limit explicitly compared in the note."""
    if UNCERTAIN_NOTE.search(text) or re.search(r"\bnot\s+(?:above|below)\b", text):
        return False
    temperatures = list(re.finditer(r"\b(\d+(?:\.\d+)?)\s*c\b", text))
    if len(temperatures) != 2 or not re.search(
        r"\b(?:chiller|probe|thermometer|ice box|warmer|cooked|fish|meat|shrimp|karne|isda|hipon)\b", text):
        return False
    first, second = temperatures
    relation = text[first.end():]
    actual, limit = Decimal(first[1]), Decimal(second[1])
    minimum = bool(re.search(r"\b(?:minimum|pinakamababa)\b", relation))
    return bool(
        (actual > limit and not minimum and re.search(r"\b(?:above|mas mataas|lampas)\b", relation))
        or (actual < limit and minimum and re.search(r"\b(?:below|mas mababa|mababa sa)\b", relation))
    )


def supports_category(code, text):
    if UNCERTAIN_NOTE.search(text):
        return False
    compliance = COMPLIANT_CATEGORY.get(code)
    if compliance and compliance.search(text):
        return False
    if code == "Market Rules":
        return bool(SPECIFIC_RULE_TOPICS.search(text))
    if code == "Stall Management" and re.search(r"\b(?:backlight\w*|backlit)\b", text):
        text = re.sub(r"\bnumber plate\b", "", text)
    if code in {"Permit & Licensing", "Illegal Vendor"}:
        # Construction approval and interference with an inspector have their
        # own categories even when their descriptions mention a permit.
        if (CATEGORY_PATTERNS["Stall Construction"].search(text)
                and re.search(r"\b(?:building|weld\w*|installed|itinayo|nagpatayo|pinagawa|approval application)\b", text)
                and not re.search(r"\b(?:business|meat dealer|lpg|sanitary|fire safety)\b", text)):
            return False
        if re.search(r"\b(?:presented|ipinakita|pinakita)\b.{0,90}\b(?:another person|ibang tao|ng iba|cited)\b", text):
            return False
    if (code == "DressCode" and re.search(r"\b(?:porter|kargador)\b", text)
            and not re.search(r"\b(?:sando|shirtless|apron|hairnet|slippers|gloves|barefoot)\b", text)):
        return False
    if code == "Obstruction" and not re.search(
        r"\b(?:block\w*|narrow\w*|obstruct\w*|nakaharang|harang|makitid|nakasagabal|sagabal|"
        r"stacked|lined|parked|hung|tied|strung|isinabit|itinali|nakasalansan|itinambak|ipinarada|isinampay)\b", text):
        return False
    pattern = CATEGORY_PATTERNS.get(code)
    return bool(pattern and pattern.search(text))
