"""Explainable, multilingual violation extraction and section insights.

Demo stage: lexicon/rules, no model weights and no network calls.
Descriptions produce supported action proposals or an automatic abstention.
"""
import csv
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from html import unescape
from pathlib import Path
import re
import unicodedata

from .reweigh import WEIGHT_CODE
from .description_evidence import (
    described_incidents, described_weight_outcome, directly_described_categories,
    followed_by_unconfirmed_statement, supports_category, temperature_violation,
)

ROOT = Path(__file__).resolve().parents[1]
TAGALOG = set('ang ng mga sa ay na at wala walang hindi nakaharang marumi timbangan puwesto paninda may habang daan basura kulang malakas nagtitinda'.split())
ENGLISH = set('the and with missing not expired stall blocked blocking sidewalk weighing scale garbage food pathway walkway found near during vendor noise loud'.split())
CLEAN_RE = re.compile(r'\b(?:walang nakitang paglabag|walang violation|no violations? (?:found|observed)|no infraction|no issue found|maayos ang lahat)\b', re.I)
NEGATION_RE = re.compile(r'\b(?:hindi|di|not|never|walang|no)\b', re.I)
JUNK_RE = re.compile(r'\b(?:asdf|qwerty|hikkbvfgjjgg|gjkkvvhh|xcvv|jjjk)\b', re.I)
MEASURED = r'(?:measured|reweighed|weighed|tinimbang|sinukat|actual weight)'
SPLIT_RE = re.compile(r'[,;!?]+|(?<!\d)\.|\.(?!\d)|\s+\b(?:at|tsaka|tapos|pati|also|and|plus|pero)\b\s+', re.I)
AMBIGUOUS_RE = re.compile(
    r'\b(?:pakicheck|paki check|please check|please verify|suspect(?:ed|s)?|possible|possibly|'
    r'might|maybe|could|may be|baka|posible|diumano|alleged(?:ly)?|unconfirmed)\b', re.I
)
MASS_UNITS = dict.fromkeys(('kg', 'kilo', 'kilos', 'kilogram', 'kilograms'), 1000)
MASS_UNITS.update(dict.fromkeys(('g', 'gram', 'grams', 'gramo'), 1))
MASS = r'(\d+(?:\.\d+)?)\s*(' + '|'.join(MASS_UNITS) + r')\b'
SHORT_MASS_RE = re.compile(
    rf'\b(?:advertised|declared|labeled|labelled|sold|bagged|packed|ibinenta|ibinentang|nakalagay)\s+'
    rf'(?:as |na |at )?{MASS}\s*,?\s+(?:but |pero |ngunit )?'
    rf'{MEASURED}\s+(?:at |was |only |na |lang )?{MASS}(?!\s+(?:or|o|to)\s+\d)', re.I
)
SPELLING = {'timbagan': 'timbangan', 'timbngan':'timbangan', 'madyang':'madayang', 'nakaharng':'nakaharang', 'hindiii':'hindi', 'idcard':'id card', 'nagkakalat':'nakakalat'}
MODEL_MIN_CONF = 0.78
ACCEPT_RULE_CONF = 0.93
RULE_PIPELINE_VERSION = "3.3.0-description-only"


def load_csv(name):
    with (ROOT / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def catalog():
    rows = load_csv('config/taxonomy.csv')
    taxonomy = {r['code']: r for r in rows}
    if len(taxonomy) != len(rows):
        raise ValueError('Duplicate category code in config/taxonomy.csv')
    lexicon = []
    for r in load_csv('config/lexicon.csv'):
        if r['code'] not in taxonomy:
            raise ValueError('Unrecognized lexicon code: ' + r['code'])
        lexicon.append({**r, 'regex': re.compile(r['pattern'], re.I | re.U)})
    return taxonomy, lexicon


def normalize(value):
    """Clean text without destroying meaningful negation or Tagalog words."""
    value = '' if value is None else str(value)
    value = unescape(value)
    value = re.sub(r'<[^>]*>', ' ', value)
    value = re.sub(r'[\w.\-+]+@[\w.\-]+\.[A-Za-z]{2,}', ' [EMAIL] ', value)
    value = re.sub(r'(?<!\d)(?:\+63|0)9\d[\d\s\-]{8,12}\d(?!\d)', ' [PHONE] ', value)
    value = unicodedata.normalize('NFKC', value).lower()
    value = re.sub(r'[^\w\s,;.!?\[\]\-]', ' ', value, flags=re.UNICODE)
    value = re.sub(r'[-_/]+', ' ', value)
    value = re.sub(r'([^\d])\1{3,}', lambda m: m.group(1) * 2, value)
    value = re.sub(r'\s+', ' ', value).strip()
    for typo, corrected in SPELLING.items():
        value = re.sub(r'\b' + re.escape(typo) + r'\b', corrected, value)
    return value


def detect_language(text):
    words = re.findall(r'[a-z]+', text.lower())
    tl = sum(w in TAGALOG for w in words)
    en = sum(w in ENGLISH for w in words)
    if tl and en: return 'taglish'
    if tl: return 'tl'
    if en: return 'en'
    return 'unknown'


def calamancy_tokens(text):
    """Optional Filipino linguistic preprocessing for research/model expansion.

    It is NOT an independent violation classifier. Falls back to simple tokens.
    """
    try:
        import calamancy
        if not hasattr(calamancy_tokens, '_nlp'):
            calamancy_tokens._nlp = calamancy.load('tl_calamancy_md')
        return [t.text for t in calamancy_tokens._nlp(text)]
    except (ImportError, OSError):
        return re.findall(r'\w+', text)


def split_clauses(text):
    # Keep both quantities in the same clause even when a separator occurs between them.
    pairs = [match.span() for match in SHORT_MASS_RE.finditer(text)]
    boundaries = [match.span() for match in SPLIT_RE.finditer(text)
                  if not any(start <= match.start() < end for start, end in pairs)]
    starts = [0, *(end for _, end in boundaries)]
    ends = [*(end if '?' in text[start:end] else start for start, end in boundaries), len(text)]
    return [clause for start, end in zip(starts, ends) if (clause := text[start:end].strip())]


def is_negated(clause, match, negatable):
    if not negatable: return False
    # Narrow local negation window: 'hindi madaya', 'not tampered'.
    left = clause[max(0, match.start() - 20):match.start()]
    in_span = clause[match.start():match.end()]
    if NEGATION_RE.search(left): return True
    # 'Hindi madaya ang timbangan' has negation inside the full matched regex.
    first_cue = re.search(r'\b(?:madaya(?:ng)?|rigged|tampered|dirty|marumi|nakaharang|blocked|short)\b', in_span, re.I)
    if first_cue and NEGATION_RE.search(in_span[max(0, first_cue.start()-13):first_cue.start()]): return True
    return False


def described_masses(match):
    declared, declared_unit, measured, measured_unit = match.groups()
    return Decimal(declared) * MASS_UNITS[declared_unit], Decimal(measured) * MASS_UNITS[measured_unit]


def extract_rule_mentions(clean_text, lexicon):
    found = {}
    unknown = []
    for clause in split_clauses(clean_text):
        matches = []
        if '?' not in clause and not AMBIGUOUS_RE.search(clause):
            for term in lexicon:
                for match in term['regex'].finditer(clause):
                    if not is_negated(clause, match, term['negatable'].lower() == 'true'):
                        matches.append((term['code'], float(term['confidence'])))
            for match in SHORT_MASS_RE.finditer(clause):
                declared, measured = described_masses(match)
                if not is_negated(clause, match, True) and measured < declared:
                    matches.append((WEIGHT_CODE, 0.99))
        if not matches and len(clause.split()) >= 3 and not CLEAN_RE.search(clause):
            unknown.append(clause)
        for code, confidence in matches:
            hit = {'code':code,'evidence':clause[:200], 'confidence':confidence, 'source':'rule'}
            if code not in found or hit['confidence'] > found[code]['confidence']:
                found[code]=hit
    return list(found.values()), unknown


def analyze_ticket(row, taxonomy, lexicon, classifier=None, llm=None):
    text = str(row.get('description') or '')
    clean = normalize(text)
    tid = str(row['ticket_id'])
    base = {'ticket_id':tid, 'vendor_id':str(row.get('vendor_id','')),
            'section_id':str(row.get('section_id','')), 'ticket_type':row.get('ticket_type','Ticket'),
            'issued_at':row.get('issued_at',''), 'updated_at':row.get('updated_at',''),
            'raw_char_count':len(text.strip()), 'clean_text':clean, 'language':detect_language(clean),
            'pipeline_version':getattr(classifier, 'pipeline_version', RULE_PIPELINE_VERSION),
            'status':'', 'review_reason':'', 'codes':''}
    if not clean:
        base['status']='empty';return base, []
    if JUNK_RE.search(clean) and len(clean.split()) <= 7:
        base['status']='junk'; return base, []
    if CLEAN_RE.fullmatch(clean.rstrip(' ,;.!?')):
        base['status'] = 'clear'
        return base, []
    mentions, unknown = extract_rule_mentions(clean, lexicon)
    for code, evidence in described_incidents(text, normalize):
        if code in taxonomy and not any(mention["code"] == code for mention in mentions):
            mentions.append({"code":code, "source":"rule", "confidence":0.99, "evidence":evidence[:200]})
    for code in directly_described_categories(clean):
        if code in taxonomy and not any(mention["code"] == code for mention in mentions):
            mentions.append({"code":code, "source":"rule", "confidence":0.99, "evidence":clean[:200]})
    if ("Sanitation" in taxonomy and not any(m['code'] == 'Sanitation' for m in mentions)
            and temperature_violation(clean)):
        mentions.append({'code':'Sanitation','source':'rule','confidence':0.99,'evidence':clean[:200]})
    # Weight recommendations require facts in the description. A model score
    # alone cannot distinguish an accurate reweigh from a short one.
    weight_outcome, weight_reason, weight_evidence = described_weight_outcome(clean)
    mentions = [m for m in mentions if m['code'] != WEIGHT_CODE]
    if weight_outcome == 'violation' and WEIGHT_CODE in taxonomy:
        mentions.append({'code':WEIGHT_CODE, 'source':'rule', 'confidence':0.99,
                         'evidence':weight_evidence[:200]})

    def supported(code, evidence):
        if code == WEIGHT_CODE:
            return weight_outcome == 'violation'
        statements = re.split(r"(?<=[.!?])\s+", evidence)
        return any(
            '?' not in clause and not AMBIGUOUS_RE.search(clause)
            and not CLEAN_RE.search(clause) and supports_category(code, clause)
            and not followed_by_unconfirmed_statement(statements, index)
            for index, clause in enumerate(statements)
        )

    if classifier is not None:
        minimum = 0.0 if getattr(classifier, 'uses_category_thresholds', False) else MODEL_MIN_CONF
        for suggestion in classifier.predict(clean):
            code = suggestion['code']
            if (code in taxonomy and suggestion['confidence'] >= minimum
                    and code not in {m['code'] for m in mentions} and supported(code, clean)):
                mentions.append({**suggestion, 'evidence':clean[:200], 'source':'model'})
    if llm is not None and (unknown or not mentions):
        for suggestion in llm.classify(clean, taxonomy):
            code = suggestion['code']
            evidence = suggestion.get('evidence', '')
            if (code in taxonomy and isinstance(evidence, str) and evidence.strip()
                    and evidence in clean and supported(code, evidence)
                    and code not in {m['code'] for m in mentions}):
                mentions.append({'code':code,'evidence':evidence[:200], 'confidence':0.60, 'source':'llm'})
    base['status'] = 'labeled' if mentions else 'no_signal'
    base['review_reason'] = '' if mentions else weight_reason or 'insufficient_description_evidence'
    base['codes'] = '|'.join(sorted(m['code'] for m in mentions))
    results = [
        {'ticket_id':tid,'section_id':base['section_id'],'vendor_id':base['vendor_id'],
         'ticket_type':base['ticket_type'],'issued_at':base['issued_at'],'code':m['code'],
         'ordinance_id':taxonomy[m['code']]['ordinance_id'],'evidence':m['evidence'],
         'confidence':m['confidence'],'source':m['source'],'review_status':'accepted'}
        for m in mentions
    ]
    return base, results


def process_rows(rows, taxonomy=None, lexicon=None, classifier=None, llm=None):
    taxonomy, lexicon = (taxonomy, lexicon) if taxonomy is not None else catalog()
    texts, mentions, queue=[],[],[]
    seen=set()
    for row in rows:
        obj, hits=analyze_ticket(row,taxonomy,lexicon,classifier,llm)
        key=(str(row.get('vendor_id','')),str(row.get('issued_at',''))[:10],obj['clean_text'])
        if obj['clean_text'] and key in seen:
            obj['status']='duplicate';hits=[];obj['codes']=''
        seen.add(key)
        texts.append(obj); mentions.extend(hits)
    return texts, mentions, queue


def parse_date(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (ValueError,TypeError):return None


def summarize_sections(mentions, inspections, taxonomy, section_rows, period_days=30, anchor=None):
    """Roll up accepted/human-confirmed mentions only. No zone guesses or store-count claims."""
    accepted = [m for m in mentions if m['code'] in taxonomy
                and m.get('review_status') == 'accepted']
    all_dates=[parse_date(m.get('issued_at')) for m in accepted]
    all_dates=[d for d in all_dates if d]
    from datetime import timedelta
    if anchor is None: anchor=max(all_dates) if all_dates else datetime.now().astimezone()
    window_start=anchor-timedelta(days=period_days)
    result=[]
    for sec in section_rows:
        sid=str(sec['section_id']); section_name=sec['section_name']
        data=[m for m in accepted if str(m['section_id'])==sid and (d:=parse_date(m.get('issued_at'))) and window_start<=d<=anchor]
        inspected=[r for r in inspections if str(r['section_id'])==sid and (d:=parse_date(r.get('inspected_at'))) and window_start<=d<=anchor]
        groups=defaultdict(list)
        for m in data: groups[m['code']].append(m)
        def impact(code):
            return sum(int(taxonomy[code]['severity'])*(0.5 if x.get('ticket_type','').lower()=='warning' else 1.0) for x in groups[code])
        best = max(groups, key=lambda k:(impact(k),len(groups[k]),k)) if groups else ''
        risk_score=round(sum(impact(k) for k in groups),2)
        risk='High' if risk_score>=14 else 'Moderate' if risk_score>=8 else ('Low' if data else 'Insufficient data')
        n_inspections=len({str(x['inspection_id']) for x in inspected})
        pattern_confidence=('High' if n_inspections>=8 else 'Medium' if n_inspections>=5 else 'Low') if n_inspections else 'Unknown'
        hourly=Counter(parse_date(x['issued_at']).hour for x in {m['ticket_id']:m for m in data}.values())
        peak_hour=max(range(24),key=lambda start:(sum(hourly[(start+i)%24] for i in range(3)),-start)) if data else None
        peak=f'{peak_hour:02d}:00–{(peak_hour+3)%24:02d}:00' if peak_hour is not None else ''
        last_flagged=max((parse_date(x['issued_at']) for x in data),default=None)
        result.append({'section_id':sid,'section_name':section_name,'ticket_mentions':len(data),
          'inspections_sampled':n_inspections,'prominent_code':best,
          'prominent_violation':taxonomy[best]['name_en'] if best else '',
          'recommended_action':taxonomy[best]['action_template_en'] if best else '',
          'peak_time':peak,'pattern_confidence':pattern_confidence,'risk_score':risk_score,'risk_level':risk,
          'last_flagged':last_flagged.isoformat() if last_flagged else '',
          'window_start':window_start.isoformat(),'window_end':anchor.isoformat()})
    return sorted(result,key=lambda r:(-r['risk_score'],r['section_id']))


def write_csv(path, rows, headers=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fields=headers or (list(rows[0]) if rows else [])
    if not fields:return
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
