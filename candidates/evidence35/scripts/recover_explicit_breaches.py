"""Select and replay additive evidence checks without changing the default pipeline."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from recover_corroborated_recall import ROOT, digest, incident_spans, load, metrics, normalize, sources
from scripts.observed_breach_recovery import grounded_codes


PRIOR = ROOT / 'evaluation/operational-evidence-recall-v4'


def collect(name):
    references, seed, _, _, _, _, identity = sources(name)
    path = PRIOR / (name + '.json')
    prior = load(path)
    for filename, expected in prior['scoring_identity'].items():
        if digest(ROOT / filename) != expected:
            raise ValueError(f'Prior scoring code changed: {filename}')
    decisions = prior['decisions']
    if len(seed) != len(decisions) or any(old['scenario_id'] != new['scenario_id']
                                         for old, new in zip(seed, decisions)):
        raise ValueError('Prior cohort ordering changed')
    pairs = set()
    for index, (reference, prior_row) in enumerate(zip(references, decisions)):
        for unit in incident_spans(reference['description'], normalize):
            pairs.update((index, code) for code in grounded_codes(unit) if code not in prior_row['predicted_codes'])
    identity[path.relative_to(ROOT).as_posix()] = digest(path)
    return decisions, sorted(pairs), identity


def select_categories(decisions, pairs):
    correct = defaultdict(set)
    blocked = set()
    for index, code in pairs:
        row = decisions[index]
        if row['expected_decision'] == 'accept' and code in (row['expected_codes'] or ()):
            correct[code].add(row['scenario_id'])
        else:
            blocked.add(code)
    return sorted(code for code, scenarios in correct.items() if code not in blocked and len(scenarios) >= 2)


def replay(decisions, pairs, categories):
    accepted = [set(row['predicted_codes']) for row in decisions]
    for index, code in pairs:
        if code in categories:
            accepted[index].add(code)
    return [dict(row, predicted_codes=sorted(prediction)) for row, prediction in zip(decisions, accepted)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--regressions', action='store_true')
    args = parser.parse_args()
    paths = (Path(__file__), ROOT / 'scripts/observed_breach_recovery.py')
    identity = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    if args.regressions:
        frozen = load(args.output / 'validation_verified.json')
        if frozen['identity'] != identity or not frozen['categories']:
            raise ValueError('No unchanged validation selection to replay')
        categories = frozen['categories']
        cohorts = ('test_regression_verified', 'challenge_verified')
    else:
        args.output.mkdir(exist_ok=False)
        cohorts = ('validation_verified',)
    for name in cohorts:
        decisions, pairs, source_identity = collect(name)
        if not args.regressions:
            categories = select_categories(decisions, pairs)
        result = replay(decisions, pairs, categories)
        report = {'purpose': 'previously_inspected_development_regression', 'identity': identity,
                  'source_artifacts_sha256': source_identity, 'categories': categories, 'candidate_pairs': len(pairs),
                  'prior_metrics': metrics(decisions), 'metrics': metrics(result), 'decisions': result}
        with (args.output / (name + '.json')).open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
            handle.write('\n')
        print(name, categories, report['metrics'], flush=True)


if __name__ == '__main__':
    main()
