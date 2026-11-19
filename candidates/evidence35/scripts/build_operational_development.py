"""Prepare incident annotations from the two previously supplied real-record batches."""
import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parents[3]
MARKET = 'market_inspection_eval_multilabel.csv'
WEIGHT = 'weightmeasures_eval_120 real records descrpitions.csv'
STATES = ('supported', 'compliant', 'insufficient')
FIELDS = 'record_id group_id language description incident_id category evidence_state evidence_quote label_note'.split()
STALL = re.compile(r'\b[A-Z]-\d{2}\b')

# These describe the repeated observations in this source batch only.
# They are offline annotations and are never imported by the application.
MARKET_FINDINGS = {
    'Vendor Identification': r'vendor ID in a drawer|tindera na nagbebenta walang suot',
    'Permit & Licensing': r'walang health certificate|permit is for dry goods',
    'Sanitation': r'nagtatapon ng kaliskis|uncovered fish|cooked food left uncovered',
    'WeightMeasures': r'calibrated na Timbangan Bayan|reweighed at Timbangan Bayan|registration seal|may magnet',
    'Lighting & Energy': r'halogen lamps|electric stove',
    'Stall Occupancy': r'ibang tao ang nagtitinda|selling from the adjacent vacant stall',
    'Stall Management': r'no fire extinguisher',
    'Stall Construction': r'counter extension built|second-level na shelf',
    'Utilities': r'illegal jumper|walang grease trap',
    'Stall Rental': r'subleasing|rent ledger shows',
    'Illegal Vendor': r'hawker selling fruit|nagtitinda ng gulay sa sidewalk',
    'Public Order': r'in a fistfight|loud sigawan',
    'Liquor': r'drinking gin',
    'Market Conduct': r'grabbed a shopper|minura ng tindero',
    'Obstruction': r'fully block the fire exit|chopping table placed in the aisle',
    'DressCode': r'tindero naka-sando|vendor handling fish without an apron',
    'Bladed Instruments': r'knives left on the counter after closing|vendor carried an uncovered bolo',
    'Traffic': r'tricycle-ban zone|loading-prohibited marked zone',
    'Porter Regulation': r'has no porter ID|porter charged P150',
    'Promotions': r'free-taste sampling|raffle sa pwesto',
    'Advertising': r'namimigay ng flyers',
    'Signage & Streamers': r'after its approved display period|tarpaulin sign mas malaki',
    'Entertainment Activities': r'karaoke event|concert ran two hours past',
    'Lighting Facilities': r'stall.s own light fixture|sirang ilaw ng pwesto',
    'Market Rules': r'using it as a dwelling|aso ng tindero|kids playing',
    'Price Monitoring': r'walang price tag|posted price P180/kg',
    'Market Fees & Surcharges': r'without paying the double rate|daily market fee unpaid',
    'Resisting Authority': r'tinulak ng tindero ang enforcer|took back the confiscated scale',
    'General Penalties': r'closure order from last week is in force|suspendido ang lisensya',
}
MARKET_COMPLIANCE = {
    'Vendor Identification': r'vendor ID worn and valid',
    'Permit & Licensing': r'business permit current|health certificate on file',
    'Sanitation': r'garbage in sealed bags|fish on ice and covered',
    'WeightMeasures': r'reweigh of 1 kg tilapia came to 1,010 g',
    'Stall Occupancy': r'occupied by the awardee',
    'Stall Management': r'fire extinguisher present and in date',
    'Utilities': r'may grease trap at malinis ang lababo',
    'Stall Rental': r'rent paid up to date per ledger',
    'Obstruction': r'aisle in front of the stall is clear',
    'DressCode': r'naka-apron at maayos ang suot',
    'Bladed Instruments': r'knives in a locked steel box',
    'Traffic': r'delivery used the designated loading area',
    'Porter Regulation': r'kargador may valid ID at tama ang singil',
    'Signage & Streamers': r'streamer within approved display period',
    'Lighting Facilities': r'stall light working',
    'Price Monitoring': r'price board updated, prices match charges',
    'Market Fees & Surcharges': r'daily fee paid, resibo ipinakita',
}
MARKET_INSUFFICIENT = (
    ('Vendor Identification', r'unclear if selling', 'Active selling and an ID breach were not established.'),
    ('Liquor', r'smell of alcohol', 'No sale or consumption was observed.'),
    ('Liquor', r'nagbebenta ng beer', 'The note describes sale by the bottle without establishing drinking, serving, or dispensing.'),
    ('Stall Rental', r'rent may be behind', 'The rent ledger was not checked.'),
    ('WeightMeasures', r'buyer said the scale felt off', 'No reweigh or scale test was performed.'),
    ('Permit & Licensing', r'may tsismis na walang permit', 'The permit report was unverified.'),
    ('Obstruction', r'crates near the aisle', 'No restriction of passage was established.'),
    ('Stall Construction', r'new shelf at the stall', 'Approval status was not checked.'),
    ('Lighting Facilities', r'light in the stall flickering', 'The stallholder maintenance duty was unknown.'),
    ('Public Order', r'vendor and buyer argued briefly', 'The note establishes a disagreement without the disorder required for this category.'),
    ('Public Order', r'loud music from the area', 'The responsible stall and disruptive effect were not established.'),
    ('Advertising', r'may flyers sa sahig', 'The distributor and any breached condition were not established.'),
    ('Bladed Instruments', r'knife on the counter while', 'The note gives no breached handling or storage condition during active use.'),
    ('General Penalties', r'closure order mentioned by a neighbor', 'The order was not verified as active.'),
    ('Market Conduct', r'anonymous complaint the vendor was rude', 'No specific conduct was described.'),
    ('Advertising', r'brand ad posters', 'The note establishes a missing approval record without confirming that required approval was absent.'),
    ('Stall Management', r'fire extinguisher expired', 'The note does not identify the applicable stallholder duty.'),
)
FINDING_NOTES = {
    'Vendor Identification': 'The seller did not display or produce the required ID.',
    'Permit & Licensing': 'The stated activity lacks the required certificate or exceeds the documented permit scope.',
    'Sanitation': 'The note describes an observed waste disposal or food handling failure.',
    'WeightMeasures': 'The note documents a reference reweigh below the declared quantity, a scale defect, or missing registration seal.',
    'Lighting & Energy': 'The observed equipment conflicts with the stated restriction.',
    'Stall Occupancy': 'The seller or space used differs from the stall award.',
    'Stall Management': 'The extinguisher required under the stated duty is absent.',
    'Stall Construction': 'The completed alteration lacks approval or exceeds the approved plan.',
    'Utilities': 'The stall has an unauthorized utility connection or lacks a required grease trap.',
    'Stall Rental': 'The note documents unpaid rent or a sublease that the lease prohibits.',
    'Illegal Vendor': 'The note places a seller at a specific location without the applicable authorization.',
    'Public Order': 'The disturbance is tied to a concrete disruption of market activity.',
    'Liquor': 'The note reports a vendor drinking at the stall during selling hours.',
    'Market Conduct': 'The note describes the specific conduct directed at a shopper.',
    'Obstruction': 'The stall item blocks an exit or measurably narrows the aisle.',
    'DressCode': 'The observed attire conflicts with the requirement for the vendor activity.',
    'Bladed Instruments': 'The note documents unsecured storage after closing or carrying an uncovered blade outside the vending area.',
    'Traffic': 'The delivery vehicle is in a zone where the stated restriction applies.',
    'Porter Regulation': 'The note documents a porter ID or registration lapse, or a charge above the posted rate.',
    'Promotions': 'The promotion lacks approval or fails to deliver its approved prize.',
    'Advertising': 'The note documents distribution without approval.',
    'Signage & Streamers': 'The sign exceeds its approved dimensions or display period.',
    'Entertainment Activities': 'The event lacks approval or exceeded its approved end time.',
    'Lighting Facilities': 'The observed fixture failure is paired with a stated vendor maintenance duty.',
    'Market Rules': 'The observed stall use or conduct matches the relevant working operating rule.',
    'Price Monitoring': 'The required displayed price is absent or the verified charge exceeds it.',
    'Market Fees & Surcharges': 'The ledger confirms the fee or surcharge was unpaid.',
    'Resisting Authority': 'The note describes physical interference with an enforcement action.',
    'General Penalties': 'The stall is still operating while the stated order or suspension is active.',
}
COMPLIANCE_NOTES = {
    'Vendor Identification': 'The vendor ID is valid and displayed.',
    'Permit & Licensing': 'The applicable permit is current or the certificate is on file.',
    'Sanitation': 'The note describes the checked food protection or waste storage condition.',
    'WeightMeasures': 'The reweigh met the declared quantity.',
    'Stall Occupancy': 'The actual occupant matches the awardee.',
    'Stall Management': 'The extinguisher is present and in date.',
    'Utilities': 'The sink has a grease trap.',
    'Stall Rental': 'The ledger confirms that rent is current.',
    'Obstruction': 'The passage was observed clear.',
    'DressCode': 'The observed vendor was wearing an apron and appropriate attire.',
    'Bladed Instruments': 'The knives were secured in a locked box.',
    'Traffic': 'The delivery used the designated loading area.',
    'Porter Regulation': 'The porter had a valid ID and charged the correct amount.',
    'Signage & Streamers': 'The streamer was within its approved display period.',
    'Lighting Facilities': 'The checked stall light was working.',
    'Price Monitoring': 'The posted prices matched the amounts charged.',
    'Market Fees & Surcharges': 'A receipt confirmed payment of the daily fee.',
}


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def market_annotations(description):
    pieces = re.split(r';\s*(?:also\s+)?|,\s*tapos\s+|(?<!\b[A-Z])\.\s+', description)
    quotes = []
    for piece in pieces:
        if re.match(r'stallholder must maintain', piece, re.I):
            previous = quotes.pop()
            start = description.index(previous)
            end = description.index(piece, start + len(previous)) + len(piece)
            quotes.append(description[start:end])
        else:
            quotes.append(piece)
    for quote in quotes:
        quote = re.sub(r'^(?:(?:stall|pwesto|inspection at) )?\[stall\]\s*[:–-]\s*', '', quote, flags=re.I)
        quote = re.sub(r'\s*\(\[stall\]\)(?=\.?$)', '', quote).strip(' .')
        matches = [
            (code, state, '')
            for catalog, state in ((MARKET_FINDINGS, 'supported'), (MARKET_COMPLIANCE, 'compliant'))
            for code, pattern in catalog.items()
            if re.search(pattern, quote, re.I)
        ]
        matches.extend((code, 'insufficient', note) for code, pattern, note in MARKET_INSUFFICIENT if re.search(pattern, quote, re.I))
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one annotation for {quote!r}, got {matches!r}')
        code, state, note = matches[0]
        if state == 'supported':
            note = FINDING_NOTES[code]
        elif state == 'compliant':
            note = COMPLIANCE_NOTES[code]
        yield code, state, quote, note


def weight_annotation(row, description):
    text = description.casefold()
    state = {'violation': 'supported', 'compliant': 'compliant'}[row['gold_outcome']]
    note = {
        'supported': 'The description records a short reference reweigh or documents the inspected scale fault or registration lapse.',
        'compliant': 'The note records a satisfactory reweigh or confirms the specific scale condition that was checked.',
    }[state]
    if re.search(r'kulang ang timbang.*totoong timbang|pero pag tinimbang|reweigh:', text):
        state, note = 'insufficient', 'The quantities are present, but the note does not identify a verified measurement or reference scale.'
    elif re.search(r'itinago|second scale was found|walang tinago|all scales .* exhibited', text):
        state, note = 'insufficient', 'This observation concerns scale disclosure during inspection. It does not establish the measurement result or a scale condition covered by the current category.'
        if 'both registered' in text:
            state, note = 'compliant', 'The note explicitly confirms that both inspected scales were registered.'
    elif re.search(r'naputol ang seal wire|seal wire .* broke accidentally|putol ang seal wire', text):
        state, note = 'insufficient', 'The broken seal is documented. The note does not establish the scale use or applicable reporting condition needed to resolve this incident.'
    elif re.search(r'luma na ang seal|still carries a 2023 seal', text):
        state, note = 'insufficient', 'The seal age is stated. The note does not establish the applicable renewal deadline or verify that registration was overdue.'
    return 'WeightMeasures', state, description, note


FILIPINO = re.compile(r'\b(?:ang|ng|sa|na|may|walang|wala|tapos|daw|hindi|pwesto|resibo|timbangan|tindero|kargador)\b', re.I)
ENGLISH = re.compile(r'\b(?:the|with|was|are|shows|working|without|from|vendor|reference|for|posted|left|used|rate|complaint|confirmed|per|selling|inside|no|sale|has|present|registration|permit|an|by)\b', re.I)


def language_of(text):
    observation = re.sub(r'^(?:(?:stall|pwesto|inspection at)\s+)?\[stall\]\s*[:–-]\s*', '', text, flags=re.I)
    observation = re.sub(r'\bTimbangan Bayan\b', '', observation, flags=re.I)
    if FILIPINO.search(observation):
        return 'taglish' if ENGLISH.search(observation) else 'fil'
    return 'en'


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def build(source_dir):
    rows = []
    by_record = {}
    source_counts = {}
    record_source = {}
    seen = set()
    groups = {}
    excluded = []
    changes = []
    for filename in (MARKET, WEIGHT):
        sources = read_csv(source_dir / filename)
        included = 0
        for source in sources:
            original = source['description']
            description = STALL.sub('[stall]', original)
            key = normalize(description)
            if key in seen:
                excluded.append({'file': filename, 'source_record': source['record_id'], 'reason': 'duplicate wording after stall anonymization'})
                continue
            seen.add(key)
            included += 1
            record_id = f'R{len(by_record)+1:03}'
            stalls = set(STALL.findall(original))
            if len(stalls) > 1:
                raise ValueError(f'Confirm grouping for record with several stall IDs: {source["record_id"]}')
            group_key = next(iter(stalls)) if stalls else (filename, source['vendor_id'])
            group_id = groups.setdefault(group_key, f'G{len(groups)+1:03}')
            items = list(market_annotations(description)) if filename == MARKET else [weight_annotation(source, description)]
            evidence_states = {code: state for code, state, _, _ in items}
            original_supported = set(filter(None, source['gold_codes'].split('|'))) if filename == MARKET else (
                {'WeightMeasures'} if source['gold_outcome'] == 'violation' else set()
            )
            unsupported = original_supported - {code for code, state, _, _ in items if state == 'supported'}
            if unsupported - evidence_states.keys():
                raise ValueError(f'Source label has no incident annotation: {source["record_id"]}')
            if filename == MARKET and {code for code, state, _, _ in items if state == 'supported'} - original_supported:
                raise ValueError(f'Unexpected new supported category: {source["record_id"]}')
            for i, (category, state, quote, note) in enumerate(items, 1):
                if category in unsupported or (filename == WEIGHT and state == 'insufficient' and source['gold_outcome'] == 'compliant'):
                    changes.append({'record_id': record_id, 'category': category, 'state': state, 'reason': note})
                row = (record_id, group_id, language_of(description), description, f'I{i:02}', category, state, quote, note)
                rows.append(dict(zip(FIELDS, row)))
            by_record[record_id] = [item[1] for item in items]
            record_source[record_id] = {'file': filename, 'source_record': source['record_id']}
        source_counts[filename] = {'source_rows': len(sources), 'included_records': included, 'sha256': sha256((source_dir / filename).read_bytes()).hexdigest()}
    return rows, by_record, source_counts, record_source, excluded, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_dir', type=Path)
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--check', action='store_true', help='Validate without writing outputs')
    args = parser.parse_args()
    rows, by_record, sources, record_source, excluded, changes = build(args.source_dir)
    catalog = [row['code'] for row in read_csv(ROOT / 'config/taxonomy.csv')]
    coverage = defaultdict(Counter)
    records_by_language = defaultdict(set)
    keys = set()
    for row in rows:
        key = (row['record_id'], row['incident_id'], row['category'])
        assert key not in keys
        keys.add(key)
        assert row['category'] in catalog and row['evidence_state'] in STATES
        assert row['evidence_quote'] and row['evidence_quote'] in row['description']
        assert row['label_note']
        assert all(not value.lstrip().startswith(('=', '+', '-', '@')) for value in row.values())
        coverage[row['category']][row['evidence_state']] += 1
        records_by_language[row['language']].add(row['record_id'])
    counts = {
        'descriptions': len(by_record),
        'incident_rows': len(rows),
        'multiple_incident_descriptions': sum(len(v) > 1 for v in by_record.values()),
        'mixed_supported_and_other_descriptions': sum('supported' in v and len(set(v)) > 1 for v in by_record.values()),
        'categories_with_any_examples': len(coverage),
        'categories_with_all_three_states': sum(all(counter[state] for state in STATES) for counter in coverage.values()),
        'category_state_cells_meeting_five': sum(counter[state] >= 5 for counter in coverage.values() for state in STATES),
        'category_state_cells_total': len(catalog) * len(STATES),
        'rows_by_state': dict(Counter(row['evidence_state'] for row in rows)),
        'descriptions_by_language_heuristic': {key: len(values) for key, values in records_by_language.items()},
    }
    print(json.dumps(counts, indent=2))
    if args.check:
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / 'operational_development.csv'
    with output.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    assert read_csv(output) == rows
    audit = {
        'purpose': 'Previously inspected development data. Exclude from independent validation and final test.',
        'annotation': 'Source-specific incident review against the frozen catalog, archived working policy, and description text. No model predictions or external verification fields were used. Labels are development annotations without independent adjudication.',
        'anonymization': 'Source notes were provided anonymized. Stall codes were replaced with [stall], and source identifiers are confined to this local provenance audit.',
        'grouping': 'Same reported stall grouped across batches. A note lacking a stall falls back to its source vendor pseudonym. Source vendor IDs and stall IDs do not consistently correspond. Repeated incident templates occur across stall groups. Keep these batches together and obtain validation and test from separate sources.',
        'other_sources_excluded': 'The revised weight files do not document which cases are new operational observations. The inspection pilot and legacy human review lack sufficient operational provenance. The field training workbook marks its records synthetic.',
        'csv_sha256': sha256(output.read_bytes()).hexdigest(),
        'sources': sources,
        'counts': counts,
        'shortfall_against_collection_targets': {
            'distinct_descriptions': max(0, 300 - counts['descriptions']),
            'multiple_incident_descriptions': max(0, 120 - counts['multiple_incident_descriptions']),
            'mixed_supported_and_other_descriptions': max(0, 50 - counts['mixed_supported_and_other_descriptions']),
        },
        'coverage': {code: {state: coverage[code][state] for state in STATES} for code in catalog},
        'shortfall_to_five_per_category_and_state': {
            code: {state: max(0, 5 - coverage[code][state]) for state in STATES} for code in catalog
        },
        'record_provenance': record_source,
        'duplicate_exclusions': excluded,
        'source_outcome_differences': changes,
    }
    with (args.output_dir / 'coverage_and_provenance.json').open('x', encoding='utf-8') as handle:
        json.dump(audit, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
