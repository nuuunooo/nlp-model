"""Fit a separate lexical evidence model and require incident-level corroboration."""
import argparse
from collections import defaultdict
from itertools import product
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from recover_corroborated_recall import ARTIFACT, MODEL, ROOT, FrozenEncoderScorer, digest, eligible, incident_spans, load, metrics, normalize, sources, verify_breach
from recover_neighbor_evidence import DATA, OPS, jsonl
from src.engine import catalog
from train_evidence_verifier import operational_examples, weights_for


PRIOR = ROOT / 'evaluation/operational-evidence-recall-grounded-v2'


def fit(model):
    metadata = model.verifier.metadata
    for filename, sha in metadata['data_sha256'].items():
        if digest(DATA / filename) != sha:
            raise ValueError('Synthetic evidence data changed')
    rows = jsonl(DATA / 'fit.jsonl')
    validation = jsonl(DATA / 'validation.jsonl')
    for row in rows + validation:
        row['description'] = normalize(row['description'])
    catalog_rows, _ = catalog()
    operational, provenance = operational_examples(OPS, validation, list(catalog_rows))
    if provenance != metadata['operational_fit_only']:
        raise ValueError('Operational evidence data changed')
    rows.extend(operational)
    texts = [row['description'] for row in rows]
    vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2, sublinear_tf=True)
    vectors = vectorizer.fit(list(dict.fromkeys(texts))).transform(texts)
    weights = weights_for(rows)
    category = np.array([row['target_code'] for row in rows])
    labels = np.array([row['evidence_state'] == 'supported' for row in rows])
    classifiers = {}
    for code in catalog_rows:
        subset = category == code
        classifier = LogisticRegression(C=8, solver='liblinear', class_weight='balanced', random_state=42)
        classifier.fit(vectors[subset], labels[subset], sample_weight=weights[subset])
        classifiers[code] = classifier
    return vectorizer, classifiers


def candidates(name, scorer, lexical):
    references, seed, baseline, codes, scores, thresholds, identity = sources(name)
    prior_path = PRIOR / (name + '.json')
    prior = load(prior_path)
    for path, sha in prior['identity'].items():
        if digest(ROOT / path) != sha:
            raise ValueError(f'Prior explicit evidence code changed: {path}')
    decisions = prior['decisions']
    if len(seed) != len(decisions) or any(left['scenario_id'] != right['scenario_id'] for left, right in zip(seed, decisions)):
        raise ValueError('Prior ordering changed')
    items = []
    for index, (reference, row, old) in enumerate(zip(references, decisions, baseline)):
        existing = set(row['predicted_codes'])
        old_codes = set(old['predicted_codes'])
        for unit in incident_spans(reference['description'], normalize):
            if unit.blocked or unit.is_requirement:
                continue
            scores_in_incident = scores[unit.context]
            top = int(np.argmax(scores_in_incident))
            for position, (code, score) in enumerate(zip(codes, scores_in_incident)):
                if score < .2 or code in existing or not eligible(code, unit):
                    continue
                items.append((index, code, unit.context, float(score) / thresholds[code],
                              code in old_codes, position == top, bool(verify_breach(code, unit))))
    inputs = list(dict.fromkeys((code, text) for _, code, text, *_ in items))
    learned = scorer.score_many([{'description': text, 'target_code': code} for code, text in inputs])
    supported = dict(zip(inputs, learned[:, 0]))
    by_category = defaultdict(list)
    for code, text in inputs:
        by_category[code].append(text)
    vectorizer, models = lexical
    predictions = {}
    for code, texts in by_category.items():
        values = models[code].predict_proba(vectorizer.transform(texts))[:, 1]
        predictions.update({(code, text): value for text, value in zip(texts, values)})
    features = np.array([[ratio, old, lead, proof, supported[code, text], predictions[code, text]]
                         for _, code, text, ratio, old, lead, proof in items]).reshape(-1, 6)
    if not np.isfinite(features).all():
        raise ValueError('Non-finite evidence score')
    identity[prior_path.relative_to(ROOT).as_posix()] = digest(prior_path)
    return decisions, [(index, code) for index, code, *_ in items], features, identity


def mask(rule, features):
    ratio, agreement, leader, proof, support, lexical = features.T
    corroboration = {'agreement': agreement, 'leader': leader, 'proof': proof}[rule['method']]
    return ((corroboration > 0) & (ratio >= rule['ratio']) & (support >= rule['support'])
            & (lexical >= rule['lexical']))


def choose(decisions, pairs, features):
    expected = [set(row['expected_codes'] or ()) for row in decisions]
    base = [set(row['predicted_codes']) for row in decisions]
    safe = np.array([code in expected[index] and decisions[index]['expected_decision'] == 'accept'
                     for index, code in pairs], dtype=bool)
    rules = []
    recovered = set()
    for method in ('proof', 'agreement', 'leader'):
        best = None
        for ratio, support, lexical in product((.4, .55, .7, .85, 1., 1.2),
                                              (.25, .5, .75, .9, .99, .9999),
                                              (.55, .65, .75, .85, .9, .95, .975)):
            rule = dict(method=method, ratio=ratio, support=support, lexical=lexical)
            selected = mask(rule, features)
            if (selected & ~safe).any():
                continue
            added = {pairs[index] for index in np.flatnonzero(selected)} - recovered
            if len({decisions[index]['scenario_id'] for index, _ in added}) < 2:
                continue
            by_record = defaultdict(set)
            for index, code in recovered | added:
                by_record[index].add(code)
            exact = sum(len(expected[index]) > 1 and base[index] | codes == expected[index]
                        for index, codes in by_record.items())
            rank = (exact, len(added), lexical, support, ratio)
            if best is None or rank > best[0]:
                best = rank, rule, added
        if best is not None:
            _, rule, added = best
            rules.append(rule)
            recovered.update(added)
    return rules


def replay(decisions, pairs, features, rules):
    selected = np.zeros(len(pairs), dtype=bool)
    for rule in rules:
        selected |= mask(rule, features)
    predictions = [set(row['predicted_codes']) for row in decisions]
    for offset in np.flatnonzero(selected):
        index, code = pairs[offset]
        predictions[index].add(code)
    return [dict(row, predicted_codes=sorted(codes)) for row, codes in zip(decisions, predictions)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--regressions', action='store_true')
    args = parser.parse_args()
    scorer = FrozenEncoderScorer(ARTIFACT, MODEL)
    paths = (Path(__file__), ROOT / 'scripts/train_evidence_verifier.py', ROOT / 'scripts/recover_neighbor_evidence.py',
             ARTIFACT / 'metadata.json')
    identity = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    artifact = args.output / 'fit.joblib'
    if args.regressions:
        frozen = load(args.output / 'validation_verified.json')
        if frozen['identity'] != identity or frozen['lexical_sha256'] != digest(artifact) or not frozen['rules']:
            raise ValueError('No unchanged validated lexical rule to replay')
        rules = frozen['rules']
        lexical = joblib.load(artifact)
        cohorts = ('test_regression_verified', 'challenge_verified')
    else:
        args.output.mkdir(exist_ok=False)
        lexical = fit(scorer)
        joblib.dump(lexical, artifact, compress=3)
        cohorts = ('validation_verified',)
    for name in cohorts:
        decisions, pairs, features, source_identity = candidates(name, scorer, lexical)
        if not args.regressions:
            rules = choose(decisions, pairs, features)
        result = replay(decisions, pairs, features, rules)
        report = {'purpose': 'previously_inspected_development_regression', 'identity': identity,
                  'source_artifacts_sha256': source_identity, 'rules': rules, 'lexical_sha256': digest(artifact),
                  'prior_metrics': metrics(decisions), 'metrics': metrics(result), 'decisions': result}
        with (args.output / (name + '.json')).open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
            handle.write('\n')
        print(name, rules, report['metrics'], flush=True)


if __name__ == '__main__':
    main()
