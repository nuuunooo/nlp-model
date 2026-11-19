"""Add corroborated local findings to the recall-v2 pilot, offline only."""
import argparse
from dataclasses import dataclass
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

import numpy as np

from recover_pilot_recall import (
    ARTIFACT, COHORTS, MODEL, ROOT, STRICT, WORKSPACE, FrozenEncoderScorer, digest, eligible,
    incident_spans, inference_inputs, load, metrics, normalize, scoring_identity, verify_breach,
)
from scoped_recovery_evidence import additional_proofs


REPLAY = ROOT / 'evaluation/operational-evidence-recall-v2'
FROZEN_REPORTS = WORKSPACE / 'evaluation/multi-incident-33'
BASELINES = dict(zip(COHORTS, ('validation_regression', 'test_regression', 'challenge_report')))
SUPPORT = (.5, .75, .9, .99, .999, .9999, .99999, .999999, .9999999, 1.)
PROBABILITIES = (.65, .75, .85, .9, .95, .975, .99, .995)
MARGINS = (0., .03, .07, .12, .2, .35, .5, .7)


@dataclass(frozen=True)
class Candidate:
    record: int
    code: str
    text: str
    category_score: float
    lead: float
    category_ratio: float
    baseline_agrees: bool
    proof: bool


def sources(name):
    strict_path = STRICT / (name + '.json')
    prior_path = REPLAY / (name + '.json')
    frozen_path = FROZEN_REPORTS / (BASELINES[name] + '.json')
    cache_path = STRICT / (COHORTS[name] + '_scores.npz')
    strict, prior, frozen = map(load, (strict_path, prior_path, frozen_path))
    if prior['scoring_identity'] != scoring_identity():
        raise ValueError('Prior recovery code changed')
    if prior['verifier_metadata_sha256'] != digest(ARTIFACT / 'metadata.json'):
        raise ValueError('Verifier metadata changed')
    for path, expected in strict['source_sha256'].items():
        if digest(WORKSPACE / 'candidates/description34' / path) != expected:
            raise ValueError(f'Frozen safety source changed: {path}')
    with np.load(cache_path, allow_pickle=False) as cache:
        provenance = json.loads(str(cache['provenance']))
        scores = dict(zip(cache['texts'], cache['scores']))
    for key in ('model_sha256', 'head_sha256', 'thresholds_sha256', 'codes', 'split_sha256'):
        if provenance[key] != frozen['provenance'][key]:
            raise ValueError(f'Frozen 3.3 replay uses a different {key} for {name}')
    references = strict['decisions']
    decisions = prior['decisions']
    baseline = frozen['decisions']
    if not len(references) == len(decisions) == len(baseline):
        raise ValueError(f'Cohort size differs for {name}')
    for original, recovered, old in zip(references, decisions, baseline):
        if (original['scenario_id'] != recovered['scenario_id'] or original['scenario_id'] != old['scenario_id']
                or original['description'] != old['description']):
            raise ValueError(f'Cohort order or text differs for {name}')
    layout = [inference_inputs(row['description'], normalize) for row in references]
    layout_digest = sha256(json.dumps(layout, ensure_ascii=False).encode()).hexdigest()
    if layout_digest != provenance['inference_layout_sha256']:
        raise ValueError(f'Incident layout differs for {name}')
    thresholds_path = MODEL / 'thresholds.json'
    if digest(thresholds_path) != provenance['thresholds_sha256']:
        raise ValueError('Category thresholds changed')
    return references, decisions, baseline, provenance['codes'], scores, load(thresholds_path)['thresholds'], {
        path.relative_to(WORKSPACE).as_posix(): digest(path) for path in (strict_path, prior_path, frozen_path, cache_path)
    }


def collect(name, model):
    references, decisions, baseline, codes, scores, thresholds, identity = sources(name)
    candidates = []
    explicit = set()
    for index, (row, prior, old) in enumerate(zip(references, decisions, baseline)):
        existing = set(prior['predicted_codes'])
        agreed = set(old['predicted_codes'])
        for unit in incident_spans(row['description'], normalize):
            if unit.blocked or unit.is_requirement:
                continue
            explicit.update((index, code) for code in additional_proofs(unit) if code not in existing)
            category_scores = scores[unit.context]
            top = int(np.argmax(category_scores))
            next_best = max(category_scores[:top].max(initial=0), category_scores[top+1:].max(initial=0))
            for position, code in enumerate(codes):
                score = float(category_scores[position])
                if code in existing or score < min(PROBABILITIES) or not eligible(code, unit):
                    continue
                proof = verify_breach(code, unit)
                candidates.append(Candidate(index, code, unit.context, score,
                                            score - float(next_best) if position == top else -1.,
                                            score / thresholds[code], code in agreed, bool(proof)))
    inputs = list(dict.fromkeys((item.text, item.code) for item in candidates))
    predicted = model.score_many([{'description': text, 'target_code': code} for text, code in inputs])
    if predicted.shape != (len(inputs), 3) or not np.isfinite(predicted).all():
        raise ValueError('Invalid support scores')
    support = dict(zip(inputs, predicted[:, 0]))
    signals = {
        'support': np.array([support[item.text, item.code] for item in candidates]),
        'score': np.array([item.category_score for item in candidates]),
        'lead': np.array([item.lead for item in candidates]),
        'ratio': np.array([item.category_ratio for item in candidates]),
        'agreement': np.array([item.baseline_agrees for item in candidates], dtype=bool),
        'proof': np.array([item.proof for item in candidates], dtype=bool),
    }
    pairs = [(item.record, item.code) for item in candidates]
    explicit = sorted(explicit)
    for name, values in signals.items():
        signals[name] = np.concatenate((values, np.zeros(len(explicit), dtype=values.dtype)))
    signals['explicit'] = np.array([False] * len(pairs) + [True] * len(explicit), dtype=bool)
    signals['code'] = np.array([code for _, code in pairs + explicit], dtype=str)
    pairs.extend(explicit)
    return decisions, pairs, signals, identity


def mask_for(rule, signals):
    if rule['method'] == 'explicit':
        return signals['explicit'] & (signals['code'] == rule['category'])
    return ((signals['support'] >= rule['support']) & (signals['score'] >= rule['score'])
            & (signals['lead'] >= rule['lead']) & (signals['ratio'] >= rule['ratio'])
            & (signals[rule['method']] if rule['method'] != 'local' else True))


def variants(method):
    margins = MARGINS if method == 'local' else (-1., *MARGINS)
    for support, score, lead, ratio in product(SUPPORT, PROBABILITIES, margins, (.75, 1., 1.15)):
        yield {'method': method, 'support': support, 'score': score, 'lead': lead, 'ratio': ratio}


def choose(decisions, pairs, signals):
    expected = [set(row['expected_codes'] or ()) for row in decisions]
    allowed = np.array([code in expected[index] and decisions[index]['expected_decision'] == 'accept'
                        for index, code in pairs], dtype=bool)
    original = [set(row['predicted_codes']) for row in decisions]
    rules = []
    recovered = set()
    for code in np.unique(signals['code'][signals['explicit']]):
        rule = {'method': 'explicit', 'category': str(code)}
        mask = mask_for(rule, signals)
        if not (mask & ~allowed).any():
            rules.append(rule)
            recovered.update(pairs[index] for index in np.flatnonzero(mask))
    for method in ('agreement', 'proof', 'local'):
        best = None
        for rule in variants(method):
            mask = mask_for(rule, signals)
            if not mask.any() or (mask & ~allowed).any():
                continue
            additions = {pairs[index] for index in np.flatnonzero(mask)} - recovered
            if not additions:
                continue
            by_record = {}
            for index, code in recovered | additions:
                by_record.setdefault(index, set()).add(code)
            exact = sum(len(expected[index]) > 1 and original[index] | codes == expected[index]
                        for index, codes in by_record.items())
            rank = (exact, len(additions), rule['support'], rule['ratio'], rule['score'], rule['lead'])
            if best is None or rank > best[0]:
                best = rank, rule, additions
        if best is not None:
            _, rule, additions = best
            rules.append(rule)
            recovered.update(additions)
    return rules


def replay(decisions, pairs, signals, rules):
    accepted = [set(row['predicted_codes']) for row in decisions]
    mask = np.zeros(len(pairs), dtype=bool)
    for rule in rules:
        mask |= mask_for(rule, signals)
    for index in np.flatnonzero(mask):
        record, code = pairs[index]
        accepted[record].add(code)
    return [dict(row, predicted_codes=sorted(codes)) for row, codes in zip(decisions, accepted)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--regressions', action='store_true')
    args = parser.parse_args()
    model = FrozenEncoderScorer(ARTIFACT, MODEL)
    paths = (Path(__file__), ROOT / 'scripts/scoped_recovery_evidence.py')
    source_identity = dict(scoring_identity(), **{path.relative_to(ROOT).as_posix(): digest(path) for path in paths})
    selection_path = args.output / 'validation_verified.json'
    if args.regressions:
        frozen = load(selection_path)
        if frozen['scoring_identity'] != source_identity or frozen['verifier_sha256'] != digest(ARTIFACT / 'metadata.json'):
            raise ValueError('Model or recovery code changed since selection')
        cohorts = ('test_regression_verified', 'challenge_verified')
        rules = frozen['rules']
    else:
        cohorts = ('validation_verified',)
        args.output.mkdir(exist_ok=False)
    for name in cohorts:
        decisions, pairs, signals, identity = collect(name, model)
        if not args.regressions:
            rules = choose(decisions, pairs, signals)
        result = replay(decisions, pairs, signals, rules)
        report = {'purpose': 'previously_inspected_development_regression', 'rules': rules,
                  'scoring_identity': source_identity, 'source_artifacts_sha256': identity,
                  'verifier_sha256': digest(ARTIFACT / 'metadata.json'), 'candidate_pairs': len(pairs),
                  'prior_metrics': metrics(decisions), 'metrics': metrics(result), 'decisions': result}
        with (args.output / (name + '.json')).open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
            handle.write('\n')
        print(name, rules, report['metrics'], flush=True)


if __name__ == '__main__':
    main()
