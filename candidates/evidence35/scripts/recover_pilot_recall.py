"""Tune additive, incident-local recovery on validation, then replay the fixed rule."""
import argparse
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

import numpy as np

from evaluate_pipeline_verifier import (
    FrozenEncoderScorer, ROOT, WORKSPACE, eligible, incident_spans, inference_inputs, metrics, normalize,
)
from candidates.description34.src.breach_evidence import verify_breach


PRIOR = ROOT / 'evaluation/operational-evidence-pilot'
STRICT = WORKSPACE / 'evaluation/candidate34'
MODEL = WORKSPACE / 'models/setfit-e5-synthetic-v2'
ARTIFACT = ROOT / 'artifacts/operational-evidence-pilot'
COHORTS = {
    'validation_verified': 'validation_final',
    'test_regression_verified': 'test_regression_final',
    'challenge_verified': 'challenge_regression',
}
EVIDENCE_CUTOFFS = (.5, .75, .9, .99, .999, .9999, .99999, .999999, .9999999, 1.)
NOMINATION_RATIOS = (.25, .5, .75, 1., 1.1, 1.25, 1.5, 1.75)
LEAD_MARGINS = (0., .05, .15, .3)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def pairs_for(name, model):
    original_path = STRICT / (name + '.json')
    prior_path = PRIOR / (name + '.json')
    cache_path = STRICT / (COHORTS[name] + '_scores.npz')
    original = load(original_path)
    prior = load(prior_path)
    if (prior['base_report_sha256'] != digest(original_path)
            or prior['score_cache_sha256'] != digest(cache_path)
            or prior['verifier_metadata_sha256'] != digest(ARTIFACT / 'metadata.json')):
        raise ValueError(f'Historical replay inputs changed for {name}')
    for path, expected in original['source_sha256'].items():
        if digest(WORKSPACE / 'candidates/description34' / path) != expected:
            raise ValueError(f'Frozen safety source changed: {path}')
    references = original['decisions']
    decisions = prior['decisions']
    if len(references) != len(decisions) or any(
            left['scenario_id'] != right['scenario_id'] for left, right in zip(references, decisions)):
        raise ValueError(f'Cohort order changed for {name}')
    with np.load(cache_path, allow_pickle=False) as cache:
        provenance = json.loads(str(cache['provenance']))
        codes = provenance['codes']
        scores = dict(zip(cache['texts'], cache['scores']))
    layout = [inference_inputs(row['description'], normalize) for row in references]
    if sha256(json.dumps(layout, ensure_ascii=False).encode()).hexdigest() != provenance['inference_layout_sha256']:
        raise ValueError(f'Cached incident layout changed for {name}')
    thresholds_path = MODEL / 'thresholds.json'
    if digest(thresholds_path) != provenance['thresholds_sha256']:
        raise ValueError('Frozen category thresholds changed')
    thresholds = load(thresholds_path)['thresholds']
    if any(thresholds[code] <= 0 for code in codes):
        raise ValueError('Recovery requires positive category thresholds')
    denominators = np.array([thresholds[code] for code in codes])
    placements = []
    for index, (row, prior_decision) in enumerate(zip(references, decisions)):
        accepted = set(prior_decision['predicted_codes'])
        for unit in incident_spans(row['description'], normalize):
            if unit.blocked or unit.is_requirement:
                continue
            ratios = scores[unit.context] / denominators
            leader = int(np.argmax(ratios))
            lead_margin = float(ratios[leader] - max(ratios[:leader].max(initial=0), ratios[leader+1:].max(initial=0)))
            for position, (code, ratio) in enumerate(zip(codes, ratios)):
                if code in accepted or ratio < min(NOMINATION_RATIOS) or not eligible(code, unit):
                    continue
                margin = lead_margin if position == leader else -1.
                placements.append((index, unit.context, code, float(ratio), bool(verify_breach(code, unit)), margin))
    keys = list(dict.fromkeys((text, code) for _, text, code, _, _, _ in placements))
    values = model.score_many([{'description': text, 'target_code': code} for text, code in keys])
    if values.shape != (len(keys), 3) or not np.isfinite(values).all():
        raise ValueError('Invalid evidence scores')
    support = dict(zip(keys, values[:, 0]))
    pairs = [(index, code, ratio, proof, margin, float(support[text, code]))
             for index, text, code, ratio, proof, margin in placements]
    return decisions, pairs


def apply_rules(decisions, pairs, rules):
    predictions = [set(row['predicted_codes']) for row in decisions]
    for index, code, category_ratio, has_proof, lead, support in pairs:
        if any(support >= evidence and category_ratio >= ratio
               and (has_proof if method == 'proof' else lead >= margin)
               for method, evidence, ratio, margin in rules):
            predictions[index].add(code)
    return [dict(row, predicted_codes=sorted(prediction)) for row, prediction in zip(decisions, predictions)]


def select_rules(decisions, pairs):
    baseline = metrics(decisions)
    selected = []
    for method, margins in (('proof', (0.,)), ('lead', LEAD_MARGINS)):
        qualifying = []
        for evidence, ratio, margin in product(EVIDENCE_CUTOFFS, NOMINATION_RATIOS, margins):
            rule = (method, evidence, ratio, margin)
            result = metrics(apply_rules(decisions, pairs, [rule]))
            if (result['false_positives'] > baseline['false_positives']
                    or result['clear_false_actions'] or result['unclear_false_actions']
                    or result['multi_exact'] < baseline['multi_exact']
                    or result['true_positives'] <= baseline['true_positives']):
                continue
            rank = (result['multi_exact'], result['true_positives'], *rule[1:])
            qualifying.append((rank, rule))
        if qualifying:
            selected.append(max(qualifying)[1])
    if selected:
        result = metrics(apply_rules(decisions, pairs, selected))
        if (result['false_positives'] > baseline['false_positives']
                or result['clear_false_actions'] or result['unclear_false_actions']
                or result['multi_exact'] < baseline['multi_exact']
                or result['true_positives'] <= baseline['true_positives']):
            raise ValueError('Combined rules failed the validation gate')
    return selected


def scoring_identity():
    paths = (Path(__file__), ROOT / 'scripts/evaluate_pipeline_verifier.py',
             ROOT / 'src/evidence_verifier.py', ROOT / 'src/incidents.py', ROOT / 'src/engine.py')
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}


def save_report(output, name, rules, decisions, pairs):
    result = apply_rules(decisions, pairs, rules)
    report = {
        'purpose': 'previously_inspected_development_regression',
        'rules': rules,
        'verifier_metadata_sha256': digest(ARTIFACT / 'metadata.json'),
        'scoring_identity': scoring_identity(),
        'prior_replay_sha256': digest(PRIOR / (name + '.json')),
        'eligible_incident_category_pairs': len(pairs),
        'prior_metrics': metrics(decisions),
        'metrics': metrics(result),
        'decisions': result,
    }
    with (output / (name + '.json')).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(name, report['rules'], report['metrics'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--regressions', action='store_true', help='Replay a rule already frozen on validation')
    args = parser.parse_args()
    output = args.output
    model = FrozenEncoderScorer(ARTIFACT, MODEL)
    if args.regressions:
        frozen = load(output / 'validation_verified.json')
        if (frozen['scoring_identity'] != scoring_identity()
                or frozen['verifier_metadata_sha256'] != digest(ARTIFACT / 'metadata.json')):
            raise ValueError('Recovery code or verifier changed since validation')
        rules = frozen['rules']
        for name in ('test_regression_verified', 'challenge_verified'):
            decisions, pairs = pairs_for(name, model)
            save_report(output, name, rules, decisions, pairs)
    else:
        decisions, pairs = pairs_for('validation_verified', model)
        rules = select_rules(decisions, pairs)
        if not rules:
            print('No additive rule improved validation under the precision and safety gates.', flush=True)
            return
        output.mkdir(exist_ok=False)
        save_report(output, 'validation_verified', rules, decisions, pairs)


if __name__ == '__main__':
    main()
