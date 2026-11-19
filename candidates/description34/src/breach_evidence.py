"""Positive breach predicates shared by every recommendation source.

Classifier confidence nominates a category; it cannot establish an incident.
Fixed requirements are sourced in the versioned internal policy catalog.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from decimal import Decimal

from .description_evidence import (
    described_incidents, described_weight_outcome, directly_described_categories,
    supports_category, temperature_violation,
    QUANTITY, UNIT_DIMENSIONS, UNITS,
)
from .incidents import REQUIREMENT_START, UNCERTAIN

POLICY_PATH = Path(__file__).resolve().parents[1] / "config/evidence_policy.json"


@lru_cache(maxsize=1)
def policy_catalog():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("version") != "3.4.0-candidate" or not policy.get("source", {}).get("sha256"):
        raise ValueError("Unsupported or missing evidence policy provenance")
    return policy


def has(pattern, text):
    return bool(re.search(pattern, text, re.I))


@dataclass(frozen=True)
class Proof:
    code: str
    evidence: str
    reason: str
    policy_id: str = ""
    automatic: bool = True


# Predicates bind an observed act/failure to its object, rather than merely a topic.
PATTERNS = {
    "Vendor Identification": [
        r"\b(?:walang|no|missing|without)\s+(?:suot na |current |assigned |valid )?vendor (?:id|identification)\b(?!\s+(?:fees?|charges?))",
        r"\b(?:vendor|seller|tindero|tindera)\b.{0,35}\b(?:has no (?:current )?id|walang id)\b",
    ],
    "Permit & Licensing": [
        r"\b(?:expired|paso|walang|no|missing|without)\s+(?:na |valid |current )?(?:vendor |business |sanitary |meat dealer |lpg retail |fire safety )(?:permit|lisensya|license|certificate)\b",
        r"\b(?:business|vendor|sanitary|meat dealer|lpg retail|fire safety)\s+(?:permit|license|lisensya|certificate)\b.{0,20}\b(?:expired|paso|missing|invalid)\b",
        r"\b(?:walang|no|missing|without)\s+health certificate\b.{0,65}\b(?:cook|nagluluto|food handler)\b",
        r"\b(?:cook|food handler|nagluluto)\b.{0,55}\b(?:has no|without|walang)\s+health certificate\b",
        r"\bpermit\s+(?:is |was )?for dry goods\s+but\b.{0,45}\bselling cooked food\b",
    ],
    "Sanitation": [
        r"\b(?:marumi|dirty|unsanitary|hindi malinis)\b.{0,45}\b(?:stall|puwesto|kainan|counter|paligid)\b",
        r"\b(?:uncovered|exposed)\s+(?:yung |ang )?(?:fish|meat|food|paninda|pagkain|cooked food)\b",
        r"\b(?:nagtatapon|itinapon|dumped|dumping|dumps)\b.{0,65}\b(?:kaliskis|lamang loob|waste|garbage)\b.{0,65}\b(?:sahig|floor)\b",
        r"\b(?:garbage|trash|basura|waste)\b.{0,35}\b(?:scattered|nakakalat|tambak|improperly dumped)\b",
        r"\b(?:nakakalat|tambak)\b.{0,35}\b(?:basura|garbage|waste)\b",
        r"\b(?:cockroaches|flies|ipis|daga)\b.{0,30}\b(?:on|in|sa)\b.{0,25}\b(?:tray|food|fish|meat|pagkain|counter)\b",
    ],
    "Lighting & Energy": [
        r"\b(?:halogen|incandescent)\s+(?:lamps?|bulbs?)\b.{0,65}\b(?:in use|used|using)\b.{0,80}\b(?:allows?|required|only|eels)\b",
        r"\b(?:electric stove|cooking appliance)\b.{0,90}\b(?:bawal|prohibited|not allowed)\b",
        r"\b(?:bawal|prohibited|not allowed)\b.{0,80}\b(?:electric stove|cooking appliance)\b.{0,70}\b(?:in use|plugged|nakasaksak)\b",
        r"\b(?:colored|red|coloured)\s+(?:light|lamp|bulb)s?\b.{0,100}\b(?:make|appear|look)\b.{0,45}\b(?:fresh|fresher)\b",
    ],
    "Stall Occupancy": [
        r"\b(?:occupying|selling from|using)\b.{0,50}\b(?:adjacent|another|extra|vacant)\s+stall\b.{0,70}\b(?:not in|not covered by|outside|without)\b.{0,25}\b(?:award|lease|contract)\b",
        r"\bibang tao\b.{0,50}\bnagtitinda\b.{0,50}\bhindi\b.{0,12}\bawardee o (?:rehistradong|registered) helper\b",
        r"\b(?:occupant|occupier)\b.{0,40}\b(?:not (?:listed|named)|differs|mismatch|unauthorized)\b.{0,35}\b(?:award|contract|lease)\b",
    ],
    "Stall Construction": [
        r"\b(?:built|installed|constructed|welded|nagpatayo|nagkabit|nagdagdag|itinayo|pinagawa)\b.{0,80}\b(?:without (?:a )?(?:permit|approval)|no (?:permit|approval)|wala sa approved plan|walang (?:permit|approval))\b",
        r"\b(?:counter|extension|partition|shelf|shelves|canopy)\b.{0,45}\b(?:built|installed|constructed)\b.{0,70}\bwithout (?:a )?(?:permit|approval)\b",
    ],
    "Utilities": [
        r"\b(?:illegal|unauthorized)\s+(?:water )?(?:jumper|connection|tap)\b.{0,70}\b(?:water|sink|pipe|line)\b",
        r"\b(?:water|drainage)\b.{0,65}\b(?:unauthorized connection|illegal jumper|tampered)\b",
    ],
    "Stall Rental": [
        r"\brent ledger\b.{0,65}\b(?:unpaid|arrears|overdue)\b",
        r"\b(?:unpaid|overdue)\b.{0,40}\b(?:rent|rental)\b.{0,60}\b(?:ledger|verified records|receipt reconciliation)\b",
        r"\b(?:subleasing|subletting|sublet|sublease)\b.{0,85}\b(?:lease forbids|contract forbids|without (?:the )?(?:lessor s |city )?consent|unauthorized)\b",
    ],
    "Illegal Vendor": [
        r"\b(?:selling|nagtitinda|vending)\b.{0,100}\b(?:without|no|walang)\s+(?:a )?sidewalk permit\b",
        r"\b(?:selling|nagtitinda|vending)\b.{0,100}\b(?:sidewalk|street|bangketa)\b.{0,85}\b(?:walang|no|without)\s+(?:sidewalk |vending |special )?(?:permit|authorization|pahintulot)\b",
        r"\b(?:selling|vending)\b.{0,65}\b(?:without|no)\s+(?:vending authorization|assigned space|vending permit)\b",
    ],
    "Public Order": [
        r"\b(?:vendors?|tindero|stallholders?)\b.{0,35}\b(?:fistfight|traded punches|threw punches|nagkasuntukan)\b",
        r"\b(?:sigawan|shouting|loud argument)\b.{0,50}\b(?:vendors?|tindero)\b.{0,80}\b(?:buyers left|shoppers left|stopped selling|disrupted|natigil)\b",
    ],
    "Market Conduct": [
        r"\bminura\b.{0,35}\b(?:tindero|tindera|vendor)\b.{0,35}\b(?:mamimili|customer|buyer)\b",
        r"\b(?:vendor|seller|tindero)\b.{0,20}\b(?:grabbed|hinawakan)\b.{0,50}\b(?:shopper|customer|buyer|mamimili)\b.{0,90}\b(?:would not let go|until she bought|pinilit|refused to release)\b",
        r"\b(?:vendor|seller|tindero)\b.{0,20}\b(?:insulted|cursed|threatened|harassed)\b.{0,45}\b(?:customer|shopper|buyer|neighbor|mamimili)\b",
    ],
    "Obstruction": [
        r"\b(?:crates?|boxes|table|merchandise|goods|kahon|paninda)\b.{0,70}\b(?:block\w*|obstruct\w*|narrow\w*|nakaharang)\b.{0,45}\b(?:exit|aisle|passage|walkway|pasilyo|daan|entrance)\b",
        r"\b(?:aisle|passage|walkway|exit|pasilyo|daan)\b.{0,50}\b(?:blocked|narrowed|nakaharang)\b.{0,45}\b(?:crates?|table|goods|boxes|kahon|paninda)\b",
        r"\b(?:chopping|cutting) table\b.{0,40}\b(?:placed|left)\b.{0,35}\baisle\b.{0,45}\bnarrow\w*\b",
        r"\b(?:nakaharang|blocked|blocking|obstructed)\b.{0,55}\b(?:daan|walkway|aisle|pasilyo|exit)\b",
    ],
    "Porter Regulation": [
        r"\b(?:porter|kargador)\b.{0,65}\b(?:has no|no|walang|without)\s+(?:porter )?(?:id|registration)\b",
        r"\b(?:porter|kargador)\b.{0,65}\bnot on the roster\b",
    ],
    "Promotions": [
        r"\b(?:sampling|free taste)\b.{0,60}\b(?:booth|set up|operating|conducted)\b.{0,60}\b(?:no|without|walang)\s+(?:promotion )?approval\b",
        r"\braffle\b.{0,80}\b(?:hindi ibinigay|did not (?:give|award)|withheld|substitut\w*)\b.{0,50}\b(?:prize|premyo)\b.{0,50}\b(?:approval|approved|promised)\b",
    ],
    "Advertising": [
        r"\b(?:ad posters?|advertisements?|brand ad|advertising poster)\b.{0,70}\b(?:no|without|walang)\s+(?:advertising )?(?:approval|permit)\b",
        r"\b(?:namimigay|distributed|handing out)\b.{0,40}\bflyers\b.{0,80}\b(?:no|without|walang)\s+(?:advertising )?approval\b",
    ],
    "Signage & Streamers": [
        r"\b(?:streamer|banner|tarpaulin|sign)\b.{0,90}\b(?:past|after|beyond)\b.{0,40}\b(?:approved )?display period\b",
        r"\b(?:tarpaulin|streamer|sign|banner)\b.{0,50}\b(?:mas malaki|larger|exceeds|oversized)\b.{0,50}\b(?:approved|aprubado|allowed|limit)\b",
    ],
    "Entertainment Activities": [
        r"\b(?:vendor run|vendor organized)\b.{0,35}\b(?:karaoke|concert|event|show)\b.{0,65}\b(?:no|without|walang)\s+(?:event )?approval\b",
        r"\b(?:approved|permitted)\b.{0,35}\b(?:concert|show|event|performance)\b.{0,70}\b(?:past|beyond|after)\b.{0,35}\b(?:approved|permitted)\s+end time\b",
    ],
    "Price Monitoring": [
        r"\b(?:walang|no|missing)\s+price tags?\b.{0,65}\b(?:required|kailangan|dapat)\b",
        r"\b(?:required|mandatory)\s+(?:price display|price tags?|srp card)\b.{0,35}\b(?:absent|missing|not posted)\b",
    ],
    "Market Fees & Surcharges": [
        r"\b(?:market|daily|stall|inspection)\s+fee\b.{0,55}\b(?:unpaid|overdue|not paid)\b.{0,55}\b(?:ledger|records|verified)\b",
        r"\b(?:occupying|using)\b.{0,50}\bextra\b.{0,65}\bwithout paying\b.{0,25}\bdouble rate\b.{0,40}\bledger confirms\b",
    ],
    "Resisting Authority": [
        r"\b(?:tinulak|pushed|struck|assaulted)\b.{0,45}\b(?:enforcer|inspector|officer)\b.{0,60}\b(?:ticket|citation|inspection|duty)\b",
        r"\b(?:took back|seized|snatched|forcibly removed)\b.{0,65}\bconfiscated\b.{0,60}\binspector\b.{0,25}\b(?:force|forcibly)\b",
        r"\b(?:vendor|seller)\b.{0,40}\b(?:blocked|prevented|refused entry to)\b.{0,45}\b(?:authorized inspector|enforcer)\b",
    ],
    "General Penalties": [
        r"\bstall\b.{0,20}\bstill selling\b.{0,65}\bclosure order\b.{0,45}\bin force\b",
        r"\b(?:active|in force|current)\b.{0,25}\b(?:closure|suspension)\b.{0,85}\b(?:still selling|continued trading|open for business)\b",
        r"\bsuspendido ang lisensya hanggang\b.{0,35}\bpero bukas pa rin ang pwesto\b",
    ],
}
COMPILED = {code: [re.compile(pattern, re.I) for pattern in patterns] for code, patterns in PATTERNS.items()}
NEGATIVE_PREFIX = re.compile(r"\b(?:not|never|no|hindi|di|did not|does not|didn t)\s+(?:actually\s+)?$", re.I)
NEGATED_EVENT = re.compile(
    r"\b(?:did not|does not|never|hindi|di)\s+(?:actually\s+)?"
    r"(?:block|obstruct|dump|carry|sell|drink|grab|insult|fight|push|throw|install|construct|use)\w*\b", re.I)
RULE_ONLY = re.compile(r"^(?:rule|patakaran|requirement|req|do not|never|must not|should not|if|kung|hypothetically|example)\b|^no (?:vendor|person)\b.{0,30}\b(?:may|shall)\b", re.I)

# Broader factual failures still require a thresholded category nomination. They
# must contain an adverse observation, not a compliant mention of the topic.
FAILURES = {
    "Vendor Identification": r"never (?:been )?(?:issued|assigned)|not (?:yet )?(?:issued|assigned)|hindi pa kailanman|hindi.*nabigyan|walang sariling|not.*(?:holder|assigned)|expired|paso|ibang.*(?:pangalan|tao)",
    "Permit & Licensing": r"expired|nag expire|paso|different (?:stall|owner)|another owner|ibang (?:puwesto|may ari)|scope mismatch|not cover|hindi sakop|invalid",
    "Sanitation": r"(?:black|slimy|dirty|murky|maitim|malagkit|malabo|dumi|residue|biofilm|contaminat\w*)|(?:not|never|hindi|di).{0,20}(?:wash|clean|nilinis|hinugasan)|(?:ipis|daga|flies|cockroach\w*)",
    "Lighting & Energy": r"common outlet|shared outlet|outlet ng pasilyo|extension.{0,30}(?:aisle|pasilyo)|deceiv\w*|make.{0,30}(?:fresh|red)|(?:hindi|di).{0,20}(?:eels|metered)|non eels",
    "Stall Occupancy": r"parking|paradahan|private office|resting area|household|same house|pamilya|sambahayan|construction materials|not.{0,25}(?:award|authorized|selling)|hindi.{0,25}(?:award|pagtitinda)",
    "Stall Management": r"(?:not|never|hindi|di).{0,25}(?:report|iniulat|iniuulat|ni report)|unattended|walang bantay|(?:missing|no|walang).{0,20}(?:padlock|shutter|logbook|emergency|contact)|not.{0,20}(?:locked|updated)",
    "Stall Construction": r"without.{0,30}(?:permit|approval)|walang.{0,30}(?:permit|approval)|not.{0,25}approved|wala sa.{0,25}(?:plano|plan)|unapproved|hindi.{0,25}(?:aprubado|plano)",
    "Utilities": r"(?:installed|nagkabit|kinabit).{0,70}(?:pump|hose|bomba)|(?:waste|wasting|inasayang).{0,25}(?:water|tubig)|(?:blocked|barado|clogged).{0,30}(?:drain|pipe)|(?:unauthorized|illegal).{0,30}(?:connection|koneksyon)",
    "Stall Rental": r"(?:bounced|dishonou?red|tumalbog).{0,40}(?:check|cheque|tseke)|(?:check|cheque|tseke).{0,40}(?:bounced|dishonou?red|tumalbog)|(?:unpaid|overdue|arrears|hindi.*bayad)|(?:not|hindi|di).{0,25}(?:replaced|napalitan|replenished)|sublet|subleas",
    "Illegal Vendor": r"not.{0,40}(?:assigned|authorized|vending area)|hindi.{0,35}(?:puwesto|awtorisado)|(?:without|walang|no).{0,30}(?:authorization|permit|pahintulot)|unauthorized",
    "Public Order": r"firecracker|paputok|smoke bomb|usok|stampede|takbuhan|nagsitakbo|suntukan|fight|punch|crowd.{0,25}(?:crush|push)|nagtulakan",
    "Liquor": r"(?:opened|poured|binuksan|ibinuhos).{0,50}(?:bottle|gin|beer|alak)|(?:gin|beer|alak).{0,50}(?:opened|poured|tagay)|(?:drinking|serving|dispensing|umiinom|nag inom)",
    "Market Conduct": r"unwelcome|unwanted|remarks.{0,30}body|komento.{0,40}katawan|(?:despite|kahit).{0,40}(?:object|tumutol)|(?:phone|numero).{0,45}(?:refus|tumanggi)|(?:touched|hinawakan|sumipol)|(?:deceiv|cheat|coerc|pananakot)",
    "Obstruction": r"(?:stacked|lined|parked|hung|tied|strung|isinalansan|nakasalansan|isinabit|itinali|itinambak|isinampay|nagpatong).{0,85}(?:exit|ramp|passage|walkway|aisle|daanan|pasilyo|pinto|rampa)",
    "DressCode": r"(?:stain|mantsa|dirty|marumi|torn|punit)|(?:without|walang|missing).{0,20}(?:required apron|hairnet|gloves|boots|cap)",
    "Bladed Instruments": r"(?:sharpen\w*|naghahasa|hasa).{0,70}(?:counter|puwesto)|(?:knife|cleaver|kutsilyo).{0,50}(?:sharpen\w*|naghahasa)",
    "Traffic": r"wrong way|against.{0,20}(?:flow|traffic)|salungat|pa timog|southbound|(?:unloaded|loading|unloading|nagbaba).{0,60}(?:outside|past|lampas|bawal)|(?:parked|ipinarada).{0,40}(?:prohibited|bawal)",
    "Porter Regulation": r"(?:seven|six|five|pitong|anim|limang).{0,20}(?:sack|sako)|overload|overcharg|(?:outside|labas).{0,30}(?:assigned|zone|area)|(?:unregistered|hindi rehistrado)",
    "Promotions": r"(?:giveaway|sampling|libreng|free).{0,70}(?:children|minor|bata)|(?:different|substitut|replaced|pinalit).{0,60}(?:prize|premyo)|(?:prize|premyo).{0,40}(?:withheld|not given|hindi ibinigay)",
    "Advertising": r"(?:ad|advert\w*|anunsyo|flyer|leaflet).{0,80}(?:boycott|avoid|panis|siraan|competitor|ibang tindero)|(?:stuck|put|idinikit|dumikit).{0,45}(?:ad label|ad sticker)",
    "Signage & Streamers": r"(?:protrud\w*|extend\w*|lumampas|overhang|exceed\w*).{0,50}(?:cm|meter|pasilyo|aisle)|(?:cover\w*|takip|tinakpan).{0,50}(?:number|plate|sign)|(?:unapproved|without approval)",
    "Entertainment Activities": r"(?:speaker|tunog|sound).{0,70}(?:wet section|todo|maximum|loud|malakas)|(?:outside|past|beyond|lampas).{0,40}(?:approved|allowed|aprubado)",
    "Lighting Facilities": r"(?:dead|broken|failed|flickering|patay|sirang|sira|not working|hindi gumagana|di gumagana)",
    "Market Rules": r"smoking|naninigarilyo|cigarette|sigarilyo|service gate|delivery gate|noon washing|nagbebenta.{0,45}(?:closing|sarado)|trading.{0,30}(?:after|past|during cleaning)|(?:hindi|di).{0,25}(?:sumunod|nagsara)",
    "Price Monitoring": r"(?:per kilo|kada kilo|unit price).{0,70}(?:higher|mas mataas|mas mahal|mismatch)|(?:charged|singil|resibo).{0,60}(?:higher|mas mataas|mas mahal)|(?:not|hindi|di).{0,25}(?:posted|nakapaskil|displayed)",
    "Market Fees & Surcharges": r"(?:unpaid|overdue|outstanding|missed|late|insufficient|kulang|hindi.*bayad|hindi.*binayaran)|(?:less|mas mababa).{0,40}(?:paid|bayad)|(?:fee|collection|surcharge).{0,40}(?:short|kulang)",
    "Resisting Authority": r"(?:presented|ipinakita|pinakita).{0,75}(?:another person|ibang tao|ng iba)|(?:impersonat\w*|posing as|nagpanggap)|(?:refused|tumanggi).{0,40}(?:inspection|citation|inspector)",
    "General Penalties": r"(?:still|continued|patuloy|pa rin).{0,45}(?:selling|trading|nagbebenta|bukas)|(?:selling|trading).{0,40}(?:despite|during|kahit)",
}
MORE_FAILURES = {
    "Vendor Identification": r"photocopy|borrowed id|hindi.{0,25}orihinal|not.{0,25}original|different person|ibang tao",
    "Permit & Licensing": r"revoked|binawi|nag expire|expired",
    "Sanitation": r"mou?ld|amag|mildew|dried blood|dugo|crack\w*.{0,30}(?:dirt|residue)|(?:food|pagkain).{0,30}(?:sneeze|spit)",
    "Lighting & Energy": r"(?:freezer|chiller).{0,65}(?:stairwell|hagdanan|corridor|pasilyo|common|shared)|(?:chest freezer|chiller).{0,50}outlet",
    "Stall Occupancy": r"pribadong opisina|walang ibinebentang|household|isang pamilya",
    "Stall Management": r"disconnected number|putol na numero|(?:contact|logbook).{0,40}(?:obsolete|outdated)|(?:hindi|di).{0,20}iniuulat",
    "Stall Construction": r"approval application.{0,40}pending|nakabinbing aplikasyon|resibo lamang.{0,40}aplikasyon",
    "Utilities": r"(?:attached|nagkabit|kinabit).{0,70}(?:pump|hose).{0,35}(?:without approval|walang approval)|(?:pump|bomba).{0,80}(?:humina|pressure|without approval)",
    "Stall Rental": r"returned for insufficient funds|insufficient funds|tumalbog|bounced",
    "Public Order": r"crush|halted trading|nagsitakbo|paputok|smoke bomb",
    "Liquor": r"(?:sold|ibinenta|nagbenta).{0,50}(?:glass|tagay|baso)|(?:opened|binuksan).{0,50}(?:bottle|bote)",
    "Market Conduct": r"asking.{0,40}(?:number|phone)|komento.{0,40}katawan|hindi kanais nais|touched.{0,25}shoulder",
    "Obstruction": r"(?:ipinarada|hung|isinabit|pahalang).{0,85}(?:pintuan|corridor|pasilyo|exit)|(?:people|shoppers).{0,30}(?:bend under|could not pass)",
    "DressCode": r"caked with.{0,20}mud|dried mud|mantsa|punit",
    "Bladed Instruments": r"(?:sharpen\w*|naghahasa).{0,70}(?:sink|lababo|gilid)|(?:knives|kutsilyo).{0,50}(?:sharpen\w*|naghahasa)",
    "Traffic": r"north exit|hilagang labasan|pa timog|southbound|salungat",
    "Porter Regulation": r"(?:eight|nine|ten|walong|siyam|sampung).{0,20}(?:sacks?|sako)",
    "Promotions": r"(?:free|giveaway|energy drink|libreng).{0,70}(?:schoolchildren|minors|batang|menor de edad)",
    "Advertising": r"(?:ad|anunsyo).{0,90}(?:spoiled|named competitor|kakumpitensya|mandaraya)|(?:compared|inihambing).{0,70}(?:competitor|kakumpitensya)",
    "Signage & Streamers": r"(?:projected|protruded|extends).{0,35}(?:cm|meter)|(?:banner|karatula).{0,60}(?:katabing puwesto|neighboring stall)",
    "Entertainment Activities": r"(?:volume|tunog).{0,55}(?:past|beyond|lampas)|(?:nilakasan|raised).{0,45}(?:volume|tunog)|speaker.{0,65}wet section",
    "Lighting Facilities": r"(?:removed|tinanggal).{0,35}(?:not replaced|hindi napalitan)|(?:bulb|lamp|fixture).{0,40}removed",
    "Market Rules": r"naninigarilyo|manigarilyo",
    "Market Fees & Surcharges": r"(?:paid|binayaran).{0,30}\d+.{0,10}(?:of|sa).{0,10}\d+|hindi binabayaran",
    "Resisting Authority": r"fake name|pekeng pangalan|hid.{0,25}id|itinago.{0,25}id",
    "General Penalties": r"opened to sell|nagbukas.{0,35}ibenta|continued trading|nasa suspensyon",
}
for _code, _pattern in MORE_FAILURES.items():
    FAILURES[_code] = "(?:" + FAILURES.get(_code, "(?!)") + ")|(?:" + _pattern + ")"
OBSERVED_FAILURES = {
    "Vendor Identification": r"blurred|illegible|unreadable|malabo|hindi mabasa|covered.{0,25}(?:name|photo)",
    "Lighting & Energy": r"(?:freezer|chiller).{0,100}(?:comfort room|toilet|stairwell|hagdanan|pasilyo|corridor).{0,20}outlet",
    "Stall Occupancy": r"(?:spouse|wife|husband|asawa).{0,50}(?:award|stall|puwesto)|(?:award|stall).{0,50}(?:spouse|asawa)",
    "Stall Management": r"(?:hidden|hid|itinago).{0,50}(?:emergency|contact) card|(?:emergency|contact) card.{0,50}(?:hidden|behind|nakatago)",
    "Stall Rental": r"closed account|saradong account",
    "Public Order": r"pushing crowd|knocked over displays|nagtulakan|nagsiksikan",
    "Liquor": r"uncapped|opened.{0,40}beer|nagbukas.{0,35}(?:alak|bote)",
    "Market Conduct": r"mocked.{0,40}(?:language|customer|customer s)|refused.{0,30}(?:indigenous|religious)|tinanggihan.{0,45}katutubo",
    "DressCode": r"ripped|napunit|maputik|putik",
    "Porter Regulation": r"without.{0,20}(?:numbered )?vest|walang.{0,20}(?:vest|tsaleko)|(?:unreadable|mismatch).{0,20}(?:id|number)",
    "Advertising": r"(?:flyer|ad|poster).{0,80}(?:rival|unsafe|spoiled|mandaraya|kakumpitensya)",
    "Signage & Streamers": r"stuck out|hanging board|projected",
    "Entertainment Activities": r"(?:spectators|manonood).{0,30}(?:packed|siksik)|\d+\s+spectators|wet section",
    "Market Rules": r"smoked|nagsigarilyo|nanigarilyo",
    "Resisting Authority": r"knocked.{0,45}(?:tablet|citation|ticket)|hinampas.{0,45}(?:tablet|ticket)",
    "General Penalties": r"took orders|handed over goods|nagbukas.{0,35}(?:ibenta|magtinda)",
}
for _code, _pattern in OBSERVED_FAILURES.items():
    FAILURES[_code] = "(?:" + FAILURES[_code] + ")|(?:" + _pattern + ")"
LOCAL_FAILURES = {
    'Vendor Identification':r'folded|photo was hidden|nakatupi|nakatago ang litrato|id ng dating',
    'Permit & Licensing':r'kinansela|cancelled|canceled',
    'Lighting & Energy':r'charging.{0,30}(?:battery|device)|nagcha charge|nagcha.{0,10}charge|baterya',
    'Stall Occupancy':r'kapatid.{0,30}kasama sa bahay',
    'Stall Management':r'(?:emergency|contact) card.{0,25}blank|blangko.{0,40}(?:emergency|contact)',
    'Illegal Vendor':r'walang vending authorization',
    'Public Order':r'crowd blocked.{0,40}(?:trading stopped|halted)|nagsitakbo',
    'Liquor':r'poured.{0,30}(?:rum|gin|beer)|nagbuhos|nagbenta.{0,45}(?:beer|alak)',
    'Market Conduct':r'calling.{0,25}troublemaker|turned away.{0,40}customer',
    'DressCode':r'grease soaked|ragged|shirt.{0,25}ripped',
    'Bladed Instruments':r'honed|naghasa|hinayaan.{0,60}(?:gul\w*|maghiwa)|\d+\s*(?:year|taong)',
    'Porter Regulation':r'vest over.{0,15}arm|vest.{0,30}(?:bitbit|braso)|bitbit.{0,45}vest',
    'Promotions':r'free.{0,65}children|libreng.{0,65}bata|private\w*|pribado',
    'Advertising':r'pinangalanan.{0,80}(?:kalabang|panaderya)|(?:leaflet|flyer).{0,90}(?:iwasan|delikado)|ad texts|ad messages',
    'Signage & Streamers':r'draped.{0,50}(?:front|stall)|umabot.{0,25}\d+\s*cm|lumampas.{0,25}\d+\s*cm',
    'Entertainment Activities':r'\d+\s*(?:people|tao|mamimili)|nanonood.{0,25}konsiyerto',
    'Lighting Facilities':r'stayed off|nanatiling patay|umuugong',
    'Price Monitoring':r'bare numbers|no unit|walang yunit|numero lamang',
    'Resisting Authority':r'grabbed.{0,35}(?:test weights|citation)|tinabig.{0,35}tablet',
    'General Penalties':r'sold to|nagbukas|naghahain',
}
for _code,_pattern in LOCAL_FAILURES.items():
    FAILURES[_code] = '(?:'+FAILURES[_code]+')|(?:'+_pattern+')'
FAILURES['Vendor Identification'] += r'|former stallholder|id ng dating'
FAILURES['Lighting & Energy'] += r'|hallway lamp socket|outlet ng comfort room'
FAILURES['Lighting Facilities'] += r'|burnt out|burned out|napundi|pundi'
FAILURES['DressCode'] += r'|bare hands|kamay na walang|walang gloves'
FAILURES['Porter Regulation'] += r'|inside out|number was hidden|nakatalikod|nakatago.{0,25}numero'
FAILURES['Advertising'] += r'|photographed.{0,40}receipts|numbers to send.{0,25}ads|kinuha.{0,40}numero'
FAILURES['Signage & Streamers'] += r'|signboard.{0,35}blocked|tinakpan|tinakpan.{0,40}plaka'
FAILURES['Price Monitoring'] += r'|without saying per|walang nakasaad na yunit'
FAILURES['Resisting Authority'] += r'|yanked|hinatak|tinago.{0,25}(?:panukat|timbangan)'
FAILURES['General Penalties'] += r'|tumanggap.{0,30}order|nag abot.{0,25}paninda|nagtinda|nagbenta'
FAILURES['Promotions'] += r'|mas maaga.{0,50}bunutan|early.{0,40}(?:draw|raffle)|bunutan.{0,35}pribado'
FAILURES['Signage & Streamers'] += r'|inilatag.{0,50}tarpaulin|tarpaulin.{0,45}katabing'
FAILURES['Price Monitoring'] += r'|hindi sinasabi.{0,35}(?:kada|yunit)|walang.{0,20}yunit'
FAILURES['Lighting Facilities'] += r'|nawawala.{0,25}fixture|pundido|hindi.{0,10}bumubukas'

ADVERSE_STATES = re.compile(
    r'\b(?:missing|absent|invalid|revoked|cancelled|expired|unregistered|unpaid|overdue|'
    r'broken|burnt out|unreadable|illegible|disconnected|blank|blocked|clogged|'
    r'nawawala|sira|sirang|napundi|pundido|malabo|blangko|kinansela|binawi|'
    r'walang (?:id|permit|approval|yunit|number|numero|bantay)|'
    r'without (?:approval|permit|authorization)|not replaced|hindi napalitan)\b', re.I)
SHARED_STATE_CODES = {
    'Vendor Identification','Permit & Licensing','Stall Management','Stall Construction',
    'Utilities','Stall Rental','DressCode','Lighting Facilities','Price Monitoring','Market Fees & Surcharges',
}


def nominated_proof(code, incident):
    text, observation = incident.context, incident.text
    cue = FAILURES.get(code)
    category_matches = [m for m in re.finditer(r'\b(?:'+(cue or '(?!)')+r')\w*\b', observation, re.I)
                        if not NEGATIVE_PREFIX.search(observation[max(0,m.start()-25):m.start()])]
    shared_matches = [m for m in ADVERSE_STATES.finditer(observation)
                      if code in SHARED_STATE_CODES and supports_category(code, observation[max(0,m.start()-40):m.end()+40])
                      and not NEGATIVE_PREFIX.search(observation[max(0,m.start()-25):m.start()])]
    if not cue or not supports_category(code, text) or not any(
            not NEGATIVE_PREFIX.search(observation[max(0,m.start()-25):m.start()])
            for m in category_matches+shared_matches):
        return None
    if NEGATED_EVENT.search(observation):
        return None
    # Facts must establish duty/contradiction where a failure cue alone is ambiguous.
    if code in {"Lighting & Energy", "Stall Occupancy", "DressCode", "Bladed Instruments", "Traffic", "Porter Regulation", "Promotions", "Entertainment Activities", "Market Rules"}:
        if not has(r"\b(?:must|shall|required|rule|only|allowed|prohibited|bawal|kailangang|dapat|lamang|hanggang|requirement|aprubado|approved|patakaran|may not)\b", text):
            return None
    if code == "Stall Rental" and not has(r"\b(?:ledger|record|treasurer|tresurero|lease|contract)\b", text):
        return None
    if code == "Market Fees & Surcharges" and not has(r"\b(?:ledger|record|receipt|resibo|verified|kinumpirma|log)\b", text):
        if not (has(r'\b(?:unpaid since|unpaid for|hindi binabayaran)\b', observation)
                and has(r'\b\d+\b', observation) and not has(r'neighbor|kapitbahay|complaint|reported', observation)):
            return None
    if code == "Illegal Vendor" and not has(r"\b(?:selling|nagtitinda|nagbebenta|vendor|seller|tindero|tinderong|hawker|peddler)\b", text):
        return None
    if code == "Lighting Facilities" and not has(r"\b(?:duty|contract|agreement|kontrata|kasunduan|must|kailangang|dapat|responsib\w*)\b", text):
        return None
    if code == "Stall Occupancy" and has(r"\bdwelling\b", observation):
        return None
    if code == 'Public Order' and not has(r'firecracker|paputok|smoke bomb|stampede|nearby stalls closed|nagsitakbo|halted|stopped|natigil|knocked over|suntukan|fight|punch|nagtulakan', observation):
        return None
    if code == 'General Penalties' and not has(r'sold|selling|trading|opened to sell|took orders|handed over goods|nagbebenta|nagbenta|nagtinda|naghahain|tumanggap.{0,30}order|nag abot.{0,25}paninda|nagbukas.{0,50}(?:ibenta|magbenta)|open for business', observation):
        return None
    # A complete, explicit failure is usable as a deterministic rule too. The
    # classifier is retained for observations whose category remains implicit.
    complete = {
        'Vendor Identification','Permit & Licensing','Stall Construction',
        'Stall Management','Stall Rental','Market Conduct','Obstruction',
        'DressCode','Resisting Authority','General Penalties',
    }
    automatic = code in complete and bool(category_matches)
    if code == 'Sanitation':
        automatic = has(r'\b(?:food|fish|meat|paninda|pagkain|sangkalan|chopping|counter|tray)\b', observation)
    if code == 'Public Order':
        automatic = has(r'\b(?:vendor|seller|stallholder|tindero|may puwesto)\b', observation)
    return Proof(code, text, "explicit_failure" if automatic else "adverse_observation_with_thresholded_category_nomination", automatic=automatic)


NUMBER_WORDS = dict(zip(('one','two','three','four','five','six','seven','eight','nine','ten'), range(1,11)))
NUMBER_WORDS.update(dict(zip(('isang','dalawang','tatlong','apat','limang','anim','pitong','walong','siyam','sampung'), range(1,11))))
NUMBER = r"(?:\d+|" + '|'.join(NUMBER_WORDS) + r")"


def count_number(value):
    return int(value) if value.isdigit() else NUMBER_WORDS[value.lower()]


def quantitative_proof(code, incident):
    observation, text = incident.text, incident.context
    if code == 'Utilities' and has(r'\bcommon tap\b', observation) and has(r'\b(?:allocation|alokasyon)\b', text):
        window = re.search(r'\b(\d{1,2})(?:\s+([0-5]\d))?\s+(?:to\s+)?(\d{1,2})(?:\s+([0-5]\d))?\s*(am|pm)\b', text, re.I)
        clock = re.findall(r'\b(\d{1,2})(?:\s+([0-5]\d))?\s*(am|pm)\b', observation, re.I)
        actual = (720 if has(r'\bnoon\b', observation) else None)
        if len(clock) == 1:
            hour, minute, suffix = clock[0]
            actual = (int(hour)%12 + (12 if suffix.lower()=='pm' else 0))*60 + int(minute or 0)
        if window and actual is not None:
            suffix = 12 if window[5].lower()=='pm' else 0
            start = (int(window[1])%12+suffix)*60+int(window[2] or 0)
            end = (int(window[3])%12+suffix)*60+int(window[4] or 0)
            return not (start <= actual <= end if start <= end else actual >= start or actual <= end)
    if code == 'Traffic' and has(r'\b(?:access road|service road)\b', observation):
        mass = re.search(r'\b(\d+(?:\.\d+)?)\s+ton\w*\b', observation)
        limit = re.search(r'\bover\s+(\d+(?:\.\d+)?)\s+tons?\b', text)
        if mass and limit and has(r'\b(?:may not|prohibited|not allowed)\b', text):
            return Decimal(mass[1]) > Decimal(limit[1])
    if code == 'Porter Regulation' and has(r'\b(?:porter|kargador)\b', observation):
        actual = re.findall(r'\b(' + NUMBER + r')\s+(?:sacks?|sako)\b', observation, re.I)
        limit = re.search(r'\b(?:at most|up to|maximum(?: of)?|hanggang)\s+(' + NUMBER + r')\s+(?:sacks?|sako)\b', text, re.I)
        if len(actual) == 1 and limit:
            return count_number(actual[0]) > count_number(limit[1])
    if code == 'Bladed Instruments' and has(r'\b(?:knife|knives|cleaver|kutsilyo|blade)\b', observation):
        age = re.search(r'\b(\d+)\s*(?:year old|taong gulang)\b', observation)
        limit = re.search(r'\b(?:under|below|wala pang)\s*(\d+)\b', text)
        if age and limit:
            return int(age[1]) < int(limit[1])
    if code == 'Entertainment Activities':
        count = re.search(r'\b(\d+)\s+(?:spectators|people|shoppers|tao|mamimili|manonood)\b', observation)
        limit = re.search(r'\b(?:at most|maximum(?: of)?|hanggang)\s*(\d+)\s+(?:spectators|people|tao|manonood)\b', text)
        if count and limit:
            return int(count[1]) > int(limit[1])
    if code == 'Signage & Streamers' and has(r'project\w*|protrud\w*|extend\w*|lumampas|umabot|overhang|stuck out', observation):
        actual = [m for m in QUANTITY.finditer(observation) if UNIT_DIMENSIONS[m[2]] == 'length']
        limit = re.search(r'\b(?:more than|higit(?: sa)?|maximum(?: of)?|at most)\s+(\d+(?:\.\d+)?)\s*(cm|m|meters?|centimeters?)\b', text, re.I)
        factors = {'cm':1,'centimeter':1,'centimeters':1,'m':100,'meter':100,'meters':100}
        if len(actual) == 1 and limit:
            return Decimal(actual[0][1]) * UNITS[actual[0][2]] > Decimal(limit[1]) * factors[limit[2].lower()]
    if code == 'Price Monitoring':
        charge = re.search(r'\b(?:charged|siningil)[^\d]{0,65}(\d+(?:\.\d+)?)\b', observation, re.I)
        posted = re.search(r'\b(?:tagged|tag na|tag|posted price)\s*(?:p|php)?\s*(\d+(?:\.\d+)?)\b', observation, re.I)
        if charge and posted and has(r'\b(?:test purchase|test buy|inspector|inspektor|receipt|resibo|verified)\b', observation):
            expected = Decimal(posted[1])
            rate_unit = re.match(r'\s*(kg|g|l|ml|m|cm)\b', observation[posted.end():], re.I)
            purchase = re.search(r'\b(?:for|ang)\s*(\d+(?:\.\d+)?)\s*(kg|g|l|ml|m|cm)\b', observation[charge.end():], re.I)
            if purchase is None:
                purchase = re.search(r'\b(?:bought|bumili)[^\d]{0,60}(\d+(?:\.\d+)?)\s*(kg|g|l|ml|m|cm)\b', observation, re.I)
            if purchase and rate_unit:
                unit, denominator = purchase[2].lower(), rate_unit[1].lower()
                if UNIT_DIMENSIONS[unit] != UNIT_DIMENSIONS[denominator]:
                    return None
                expected *= Decimal(purchase[1]) * UNITS[unit] / UNITS[denominator]
            return Decimal(charge[1]) > expected
    if code == 'Market Fees & Surcharges':
        payment = re.search(r'\bpaid\s*(?:p|php)?\s*(\d+(?:\.\d+)?)\s+of\s*(?:the\s+)?(?:p|php)?\s*(\d+(?:\.\d+)?)', observation, re.I)
        if payment and has(r'\bfee\b', observation) and has(r'\b(?:log|ledger|record|receipt|verified)\b', observation):
            return Decimal(payment[1]) < Decimal(payment[2])
    return None


def matched(code, text):
    for pattern in COMPILED.get(code, []):
        for match in pattern.finditer(text):
            left = text[max(0, match.start()-25):match.start()]
            if not NEGATIVE_PREFIX.search(left) and not NEGATED_EVENT.search(match[0]):
                return match
    return None


def fixed_proof(code, key, text):
    rule = policy_catalog()["fixed_rules"].get(key)
    if rule and rule["code"] == code:
        return Proof(code, text, "internally_sourced_requirement_and_observed_breach", key)
    return None


def direct_breach(code, incident):
    """Return proof only for a definite incident; identical gate for every source."""
    if incident.blocked:
        return None
    text = incident.context
    observation = incident.text
    if "?" in text or UNCERTAIN.search(text) or RULE_ONLY.search(observation):
        return None
    # A standalone requirement is not an observation. Attached requirement context is allowed.
    if REQUIREMENT_START.search(observation):
        return None
    if code == "WeightMeasures":
        if incident.weight_blocked:
            return None
        outcome, _, evidence = described_weight_outcome(text)
        if outcome == "violation":
            return Proof(code, text, "described_quantity_comparison_or_scale_fault")
        if has(r"\b(?:scale|timbangan)\b", text) and not has(r"\b(?:not|never|hindi|di)\b.{0,12}\b(?:missing|unregistered|tampered)\b", text):
            if (has(r"\b(?:scale|timbangan)\b.{0,75}\b(?:has no|without|walang|missing)\b.{0,35}\b(?:registration seal|seal|selyo)\b", text)
                    or (has(r"\bmagnet\b.{0,50}\b(?:under|ilalim)\b.{0,40}\b(?:pan|pinggan)\b", text)
                        and has(r"\b(?:empty|walang laman)\b", text)
                        and has(r"\b(?:[1-9]\d*(?:\.\d+)?)\s*g\b", text))):
                return Proof(code, text, "observed_registration_or_empty_pan_fault")
        return None
    # These specialized parsers already require relational/quantitative facts.
    if code == "Sanitation" and temperature_violation(text):
        return Proof(code, text, "described_temperature_limit_breach")
    if code == "Sanitation" and has(r"\buncovered yung paninda\b", observation):
        return Proof(code, text, "observed_exposure_requires_category_nomination", automatic=False)
    if code in set(directly_described_categories(text)):
        return Proof(code, text, "documented_management_or_conduct_incident")
    if any(found == code for found, _ in described_incidents(text, lambda s: s)):
        return Proof(code, text, "documented_specific_incident")

    if code == "Vendor Identification":
        if has(r"\b(?:porter|kargador|mobile vendor id)\b", observation):
            return None
        if (matched(code, observation) or (has(r"\bvendor id\b.{0,45}\b(?:drawer|not displayed|not worn)\b", observation)
                and has(r"\b(?:requires|must|rule|required)\b.{0,45}\b(?:worn|displayed|display)\b", text))):
            return fixed_proof(code, "vendor_id", text)
        return None
    if code == "Permit & Licensing" and has(r"\b(?:construction|counter extension|sidewalk permit|vending permit|scale|event approval|promotion approval)\b", observation):
        return None
    if code == "Stall Management":
        if (has(r"\bextinguisher\b", observation)
                and has(r"\b(?:duty|contract|requires|must|required)\b", text)
                and (has(r"\b(?:no|missing|walang)\s+(?:fire )?extinguisher\b", observation)
                     or has(r"\bextinguisher\b.{0,25}\b(?:expired|unserviceable)\b", observation))):
            return Proof(code, text, "explicit_safety_duty_and_failure")
        return None
    if code == "Utilities" and has(r"\b(?:walang|no|missing)\s+grease trap\b", observation) and has(r"\b(?:sink|lababo|carinderia|stall)\b", text):
        return fixed_proof(code, "grease", text)
    if code == "Illegal Vendor" and has(r"\b(?:hawker|mobile vendor|peddler)\b.{0,70}\b(?:selling|vending)\b", observation) and has(r"\bno mobile vendor id on record\b", observation):
        return fixed_proof(code, "mobile_registration", text)
    if code == "Liquor":
        if (has(r"\b(?:vendor|seller|tindero)\s+(?:was |is )?(?:drinking|serving|dispensing)\b.{0,35}\b(?:gin|beer|liquor|wine|rum|alak)\b", observation)
                or has(r"\b(?:nagbebenta|selling|served|dispensed)\b.{0,30}\b(?:beer|gin|liquor|alak|wine)\b", observation)):
            return fixed_proof(code, "liquor", text)
        return None
    if code == "DressCode":
        if (has(r"\b(?:vendor|seller|tindero|tindera)\b.{0,45}\b(?:handling|selling|nagbebenta)\b.{0,40}\b(?:without|no|walang)\s+(?:an? )?apron\b", observation)
                or has(r"\b(?:vendor|seller|tindero|tindera)\b.{0,25}\b(?:naka sando|shirtless|wearing a sando)\b.{0,65}\b(?:selling|nagbebenta|handling)\b", observation)):
            return fixed_proof(code, "dress", text)
        return None
    if code == "Bladed Instruments":
        if has(r"\b(?:utensil|kitchenware)\b.{0,35}\b(?:seller|retailer|display|selling)\b|\bselling (?:utensils|kitchenware|knives)\b", text):
            return None
        if (has(r"\b(?:knives|knife|blades?|bolo)\b.{0,55}\b(?:left|kept|on the counter)\b.{0,50}\b(?:after closing|not in use|unattended)\b", observation)
                and has(r"\b(?:no locked box|unlocked|not locked|left on the counter)\b", observation)):
            return fixed_proof(code, "blade_storage", text)
        if has(r"\b(?:carried|carrying)\s+an?\s+(?:uncovered|exposed)\s+(?:bolo|knife|blade|machete)\b.{0,65}\b(?:parking|outside|another stall|street)\b", observation):
            return fixed_proof(code, "blade_carry", text)
        return None
    if code == "Traffic":
        if (has(r"\btricycle\b.{0,45}\b(?:entering|delivering|inside)\b.{0,40}\btricycle ban zone\b", observation)
                or has(r"\b(?:van|truck|vehicle|tricycle)\b.{0,55}\b(?:parked|nakaparada|unloading|loading)\b.{0,50}\b(?:prohibited|no loading|no parking)\b.{0,30}\b(?:marked|zone|lane)\b", observation)):
            return Proof(code, text, "vehicle_observed_in_explicit_restricted_zone")
        return None
    if code == "Porter Regulation" and has(r"\b(?:porter|kargador)\b", observation):
        amounts = list(re.finditer(r"\bp\s*(\d+(?:\.\d+)?)\b", observation))
        if len(amounts) == 2 and has(r"\bcharged\b", observation[:amounts[0].start()]) and has(r"\bposted rate\b", observation[amounts[0].end():amounts[1].start()]):
            if Decimal(amounts[0][1]) > Decimal(amounts[1][1]):
                return Proof(code, text, "porter_charge_exceeds_stated_rate")
    if code == "Lighting Facilities":
        if (has(r"\b(?:dead|broken|failed|flickering|patay|sirang|sira|not working)\b", observation)
                and has(r"\b(?:light|lamp|ilaw|fixture|backlight)\b", observation)
                and has(r"\b(?:stallholder|vendor|may puwesto)\b.{0,55}\b(?:maintain|maintenance|responsib|duty|provide)\w*\b|\b(?:responsibilidad|duty|contract|kontrata)\b.{0,50}\b(?:stallholder|vendor)\b|\bdapat gumagana\b", text)):
            return Proof(code, text, "fixture_failure_and_explicit_vendor_duty")
        return None
    if code == "Market Rules":
        if has(r"\b(?:vendor|seller)\b.{0,50}\b(?:sleeping|living)\b.{0,65}\b(?:dwelling|residence|home)\b", observation):
            return fixed_proof(code, "dwelling", text)
        if has(r"\b(?:vendor s|vendors|tindero|tindera)\b.{0,30}\b(?:kids|children)\b.{0,25}\bplaying\b.{0,35}\bstalls?\b", observation):
            return fixed_proof(code, "children", text)
        if has(r"\b(?:aso|dog)\b.{0,25}\b(?:tindero|vendor|seller)\b.{0,25}\b(?:nakakawala|loose|astray)\b", observation):
            return fixed_proof(code, "animals", text)
        return None
    if code == "Price Monitoring":
        amounts = list(re.finditer(r"\bp\s*(\d+(?:\.\d+)?)\b", observation))
        if (len(amounts) == 2 and has(r"\bposted price\b", observation[:amounts[0].start()])
                and has(r"\bcharged\b", observation[amounts[0].end():amounts[1].start()])
                and has(r"\b(?:same item|same unit)\b", observation)
                and has(r"\b(?:receipt shown|receipt checked|verified)\b", observation)
                and Decimal(amounts[1][1]) > Decimal(amounts[0][1])):
            return Proof(code, text, "verified_charge_exceeds_posted_price_for_same_item")

    match = matched(code, observation)
    if match:
        return Proof(code, text, "explicit_observed_category_breach")
    return None


def verify_breach(code, incident):
    if incident.blocked or incident.is_requirement:
        return None
    if "?" in incident.context or UNCERTAIN.search(incident.context) or RULE_ONLY.search(incident.text):
        return None
    text = incident.text
    if code == 'Stall Management' and has(r'\bextinguisher\b', text) and not has(r'\b(?:duty|contract|requires|must|required)\b', incident.context):
        return None
    if code == 'Resisting Authority' and has(r'\b(?:paid|binayad|binayaran|nagbayad)\b.{0,100}\b(?:posing|nagpanggap)\b', text):
        return None
    if code == 'Vendor Identification' and has(r'\b(?:inspector|enforcer|citation)\b', text) and has(r'fake name|hid.{0,20}id|pekeng pangalan|itinago.{0,20}id', text):
        return None
    if code == 'Permit & Licensing' and has(r'\b(?:storage room|raised floor|canopy|partition|cabinets?|counter|shelves|shelf|pader)\b', text) and has(r'\b(?:built|building|installed|pinagawa|itinayo|nagkabit|welded|nagdagdag)\b', text) and not has(r'\b(?:business|meat dealer|lpg retail|sanitary|health|fire safety)\b', text):
        return None
    if code == 'Sanitation' and has(r'\b(?:shirt|clothes|damit|apron|vest)\b', text) and not has(r'\b(?:food|fish|meat|paninda|pagkain|sangkalan|counter|tray)\b', text):
        return None
    if code == 'Public Order' and has(r'\b(?:observed|witnessed|watched)\b.{0,40}\b(?:shoppers|strangers|customers)\b', text):
        return None
    if code in {'Lighting & Energy','Utilities'} and has(r'\bwith (?:written |special )?approval\b|\bapproved temporary\b', text):
        return None
    if code == 'General Penalties':
        if (has(r'\b(?:lifted|expired|ended|no longer|not in force)\b', text)
                or not has(r'still serving.{0,30}suspension|closure order.{0,60}in force|active.{0,30}(?:closure|suspension)|nasa suspensyon|suspendido ang lisensya hanggang|order.{0,45}may bisa pa', text)):
            return None
    if code == 'Advertising' and has(r'\b(?:phone|numbers|numero|receipts|ad texts|ad messages)\b', text):
        if not has(r'\b(?:without consent|no consent|walang pahintulot|without permission)\b', text):
            return None
    if code == 'Liquor' and (has(r'\bno (?:one|person)\b.{0,25}\b(?:drinking|selling|serving)\b', text)
            or has(r'\b(?:no|not)\s+(?:drinking|serving|dispensing)\b', text)):
        return None
    if code == "Stall Construction" and not has(r"\b(?:counter|extension|partition|shelf|shelves|canopy|storage room|back room|storeroom|wall|pader|hollow block|renovat\w*|cabinets?|alteration|construction|built|building)\b", text):
        return None
    if code == "Permit & Licensing" and has(r"\b(?:construction|counter extension|sidewalk permit|vending permit|scale|event approval|promotion approval)\b", text):
        return None
    if code == "Vendor Identification" and has(r"\b(?:porter|kargador|mobile vendor id)\b", text):
        return None
    if code == "Bladed Instruments" and has(r"\b(?:utensil|kitchenware)\b.{0,35}\b(?:seller|retailer|display|selling)\b|\bselling (?:utensils|kitchenware|knives)\b", text):
        return None
    if code == 'Bladed Instruments' and has(r'\b(?:sharpen\w*|naghahasa)\b.{0,55}\b(?:at|sa)\s+(?:the )?(?:designated|itinakdang)\s+sharpening station\b', text):
        return None
    if code == 'Stall Rental' and has(r'\b(?:replaced the (?:bounced )?check|check was replaced|settled in full|arrears cleared)\b', text):
        return None
    quantity = quantitative_proof(code, incident)
    if quantity is not None:
        return Proof(code, incident.context, 'verified_comparison_against_explicit_limit') if quantity else None
    if code == 'Liquor' and has(r'\bliquor ban\b.{0,60}\b(?:in effect today|active|may bisa ngayong araw)\b', incident.context):
        if has(r'\b(?:sold|nagbenta|selling|nagbebenta)\b.{0,65}\b(?:beer|liquor|alak|gin)\b', text):
            return Proof(code, incident.context, 'observed_sale_during_explicit_active_ban')
    result = direct_breach(code, incident)
    if result is not None or code == "WeightMeasures":
        return result
    return nominated_proof(code, incident)
