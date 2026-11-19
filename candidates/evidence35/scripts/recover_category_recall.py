"""Try category-specific recovery only where multiple validation scenarios support it."""
import argparse
import json
from pathlib import Path

import numpy as np

from recover_corroborated_recall import (
    ARTIFACT, MODEL, ROOT, FrozenEncoderScorer, collect, digest, load, mask_for, metrics,
    replay, variants,
)


PRIOR = ROOT / 'evaluation/operational-evidence-recall-v4'


def choose(decisions, pairs, signals):
    allowed = np.array([code in (decisions[index]['expected_codes'] or ())
                        and decisions[index]['expected_decision'] == 'accept'
                        for index, code in pairs], dtype=bool)
    new = np.array([code not in decisions[index]['predicted_codes'] for index, code in pairs], dtype=bool)
    rules = []
    for category in np.unique(signals['code'][new & ~signals['explicit']]):
        same_category = (signals['code'] == category) & new
        best = None
        for method in ('agreement', 'proof', 'local'):
            for rule in variants(method):
                mask = mask_for(rule, signals) & same_category
                if (mask & ~allowed).any():
                    continue
                gained = {pairs[position][0] for position in np.flatnonzero(mask)}
                scenarios = {decisions[index]['scenario_id'] for index in gained}
                if len(gained) < 4 or len(scenarios) < 2:
                    continue
                rank = (len(scenarios), len(gained), rule['support'], rule['ratio'], rule['score'], rule['lead'])
                if best is None or rank > best[0]:
                    best = rank, dict(rule, category=str(category))
        if best is not None:
            rules.append(best[1])
    return rules


def apply_rules(decisions, pairs, signals, rules):
    # Mask each category independently. A rule never crosses into another category.
    selected = np.zeros(len(pairs), dtype=bool)
    for rule in rules:
        selected |= mask_for(rule, signals) & (signals['code'] == rule['category'])
    additions = [set(row['predicted_codes']) for row in decisions]
    for position in np.flatnonzero(selected):
        index, code = pairs[position]
        additions[index].add(code)
    return [dict(row, predicted_codes=sorted(codes)) for row, codes in zip(decisions, additions)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--regressions', action='store_true')
    args = parser.parse_args()
    prior_validation = load(PRIOR / 'validation_verified.json')
    identity = dict(prior_validation['scoring_identity'], **{Path(__file__).name: digest(Path(__file__))})
    for name, sha in prior_validation['scoring_identity'].items():
        if digest(ROOT / name) != sha:
            raise ValueError(f'Prior scoring source changed: {name}')
    if args.regressions:
        frozen = load(args.output / 'validation_verified.json')
        if frozen['scoring_identity'] != identity:
            raise ValueError('Category rule or scoring code changed after validation')
        cohorts = ('test_regression_verified', 'challenge_verified')
        rules = frozen['rules']
    else:
        cohorts = ('validation_verified',)
        args.output.mkdir(exist_ok=False)
    model = FrozenEncoderScorer(ARTIFACT, MODEL)
    for name in cohorts:
        seed, pairs, signals, _ = collect(name, model)
        prior = load(PRIOR / (name + '.json'))
        decisions = prior['decisions']
        if (prior['scoring_identity'] != prior_validation['scoring_identity']
                or prior['verifier_sha256'] != digest(ARTIFACT / 'metadata.json')
                or replay(seed, pairs, signals, prior_validation['rules']) != decisions):
            raise ValueError(f'Prior recovery is not reproducible for {name}')
        if not args.regressions:
            rules = choose(decisions, pairs, signals)
        result = apply_rules(decisions, pairs, signals, rules)
        report = {'purpose': 'previously_inspected_development_regression', 'rules': rules,
                  'scoring_identity': identity, 'prior_replay_sha256': digest(PRIOR / (name + '.json')),
                  'prior_metrics': metrics(decisions), 'metrics': metrics(result), 'decisions': result}
        with (args.output / (name + '.json')).open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
            handle.write('\n')
        print(name, rules, report['metrics'], flush=True)


if __name__ == '__main__':
    main()
