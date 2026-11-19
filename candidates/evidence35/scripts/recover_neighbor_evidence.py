"""Compare eligible incidents with fit-only evidence before adding a finding."""
import argparse
from collections import defaultdict
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

import numpy as np

from recover_corroborated_recall import (
    ARTIFACT, MODEL, ROOT, FrozenEncoderScorer, digest, eligible, incident_spans, load, metrics,
    normalize, sources,
)
from train_evidence_verifier import operational_examples
from src.engine import catalog


PRIOR = ROOT / 'evaluation/operational-evidence-recall-v4'
DATA = ROOT / 'data/evidence-v2'
OPS = ROOT / 'data/operational-development/operational_development.csv'
CACHE = ROOT / 'evaluation/evidence_embeddings_v1.npz'
FLOORS = (.35, .5, .65, .75, .85, .9, .95)


def jsonl(path):
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def encode(body, texts):
    if not texts:
        return {}
    queries = ['query: ' + text for text in texts]
    lengths = body.tokenizer(queries, truncation=False, padding=False)['input_ids']
    valid = [(text, query) for text, query, tokens in zip(texts, queries, lengths)
             if len(tokens) <= body.max_seq_length]
    if not valid:
        return {}
    return dict(zip((text for text, _ in valid), body.encode(
        [query for _, query in valid], batch_size=32, normalize_embeddings=True,
        show_progress_bar=False, convert_to_numpy=True,
    )))


def fit_bank(model):
    metadata = model.verifier.metadata
    for filename, expected in metadata['data_sha256'].items():
        if digest(DATA / filename) != expected:
            raise ValueError(f'Fit provenance changed: {filename}')
    fit = jsonl(DATA / 'fit.jsonl')
    validation = jsonl(DATA / 'validation.jsonl')
    for row in fit + validation:
        row['description'] = normalize(row['description'])
    taxonomy, _ = catalog()
    descriptions = [row['description'] for row in fit + validation]
    definitions = [normalize(code + '. ' + item['evidence_requirement_en']) for code, item in taxonomy.items()]
    order = list(dict.fromkeys(descriptions + definitions))
    with np.load(CACHE, allow_pickle=False) as cache:
        provenance = json.loads(str(cache['provenance']))
        text_digest = sha256(json.dumps(order, ensure_ascii=False).encode()).hexdigest()
        if (text_digest != provenance['input_sha256'] or provenance['encoder_sha256'] != metadata['encoder_identity']
                or provenance['normalizer_sha256'] != digest(ROOT / 'src/engine.py')):
            raise ValueError('Fit embedding cache provenance changed')
        vectors = {text: vector for text, vector, length in zip(order, cache['embeddings'], cache['lengths'])
                   if length <= model.max_length}
    operations, provenance = operational_examples(OPS, validation, list(taxonomy))
    if provenance != metadata['operational_fit_only']:
        raise ValueError('Operational fit provenance changed')
    vectors.update(encode(model.body, list(dict.fromkeys(row['description'] for row in operations
                                                       if row['description'] not in vectors))))
    examples = defaultdict(set)
    for row in fit + operations:
        if row['kind'] in {'original', 'unrelated_target'} and row['description'] in vectors:
            examples[row['target_code'], row['evidence_state'] == 'supported'].add(row['description'])
    banks = {code: tuple(np.stack([vectors[text] for text in sorted(examples[code, label])])
                         for label in (True, False)) for code in taxonomy}
    return banks


def candidates_for(name, model, banks):
    references, seed, baseline, codes, scores, thresholds, identity = sources(name)
    prior_path = PRIOR / (name + '.json')
    prior = load(prior_path)
    if prior['verifier_sha256'] != digest(ARTIFACT / 'metadata.json') or any(
            digest(ROOT / path) != value for path, value in prior['scoring_identity'].items()):
        raise ValueError('Prior replay identity changed')
    decisions = prior['decisions']
    if len(decisions) != len(seed) or any(left['scenario_id'] != right['scenario_id']
                                          for left, right in zip(decisions, seed)):
        raise ValueError('Prior replay ordering changed')
    pairs = []
    for index, (reference, row, old) in enumerate(zip(references, decisions, baseline)):
        existing = set(row['predicted_codes'])
        previous = set(old['predicted_codes'])
        for unit in incident_spans(reference['description'], normalize):
            if unit.blocked or unit.is_requirement:
                continue
            values = scores[unit.context]
            top = int(np.argmax(values))
            for position, code in enumerate(codes):
                score = float(values[position])
                if score < FLOORS[0] or code in existing or not eligible(code, unit):
                    continue
                pairs.append((index, code, unit.context, score, score / thresholds[code],
                              code in previous, position == top))
    vectors = encode(model.body, list(dict.fromkeys(item[2] for item in pairs)))
    pairs = [pair for pair in pairs if pair[2] in vectors]
    keys = list(dict.fromkeys((code, text) for _, code, text, *_ in pairs))
    grouped = defaultdict(list)
    for code, text in keys:
        grouped[code].append(text)
    similarities = {}
    for code, texts in grouped.items():
        positive, negative = banks[code]
        observed = np.stack([vectors[text] for text in texts])
        best_positive = (observed @ positive.T).max(axis=1)
        best_negative = (observed @ negative.T).max(axis=1)
        similarities.update({(code, text): (pos, pos - neg)
                             for text, pos, neg in zip(texts, best_positive, best_negative)})
    probabilities = model.verifier.probabilities(
        [{'target_code': code, 'description': text} for code, text in keys], vectors,
    ) if keys else np.zeros((0, 3))
    support = dict(zip(keys, probabilities[:, 0]))
    features = np.array([[score, ratio, old, leader, support[code, text], *similarities[code, text]]
                         for _, code, text, score, ratio, old, leader in pairs]).reshape(-1, 7)
    if not np.isfinite(features).all():
        raise ValueError('Non-finite recovery score')
    identity[prior_path.relative_to(ROOT).as_posix()] = digest(prior_path)
    return decisions, [(index, code) for index, code, *_ in pairs], features, identity


def allowed_by(rule, features):
    score, ratio, agrees, leader, support, similarity, margin = features.T
    corroborated = {'agreement': agrees > 0, 'leader': leader > 0}[rule['method']]
    return (corroborated & (score >= rule['score']) & (ratio >= rule['ratio'])
            & (support >= rule['support']) & (similarity >= rule['similarity']) & (margin >= rule['margin']))


def select(decisions, pairs, features):
    expected = [set(row['expected_codes'] or ()) for row in decisions]
    safe = np.array([code in expected[index] and decisions[index]['expected_decision'] == 'accept'
                     for index, code in pairs], dtype=bool)
    existing = [set(row['predicted_codes']) for row in decisions]
    selected = []
    recovered = set()
    for method in ('agreement', 'leader'):
        best = None
        for score, ratio, support, similarity, margin in product(
                FLOORS, (.65, .85, 1.), (.25, .5, .75, .95, .999), (.85, .9, .93), (.0, .01, .025, .05)):
            rule = dict(method=method, score=score, ratio=ratio, support=support,
                        similarity=similarity, margin=margin)
            mask = allowed_by(rule, features)
            if (mask & ~safe).any():
                continue
            additions = {pairs[i] for i in np.flatnonzero(mask)} - recovered
            if len({decisions[i]['scenario_id'] for i, _ in additions}) < 2:
                continue
            by_record = defaultdict(set)
            for index, code in recovered | additions:
                by_record[index].add(code)
            exact = sum(len(expected[i]) > 1 and existing[i] | codes == expected[i]
                        for i, codes in by_record.items())
            rank = (exact, len(additions), margin, support, similarity, ratio, score)
            if best is None or rank > best[0]:
                best = rank, rule, additions
        if best is not None:
            _, rule, additions = best
            selected.append(rule)
            recovered.update(additions)
    return selected


def replay(decisions, pairs, features, rules):
    selected = np.zeros(len(pairs), dtype=bool)
    for rule in rules:
        selected |= allowed_by(rule, features)
    codes = [set(row['predicted_codes']) for row in decisions]
    for offset in np.flatnonzero(selected):
        record, code = pairs[offset]
        codes[record].add(code)
    return [dict(row, predicted_codes=sorted(prediction)) for row, prediction in zip(decisions, codes)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--regressions', action='store_true')
    args = parser.parse_args()
    model = FrozenEncoderScorer(ARTIFACT, MODEL)
    paths = (Path(__file__), ROOT / 'scripts/recover_corroborated_recall.py', ROOT / 'scripts/train_evidence_verifier.py',
             CACHE, ARTIFACT / 'metadata.json')
    identity = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    if args.regressions:
        frozen = load(args.output / 'validation_verified.json')
        if frozen['identity'] != identity or not frozen['rules']:
            raise ValueError('No unchanged validation configuration to replay')
        cohorts = ('test_regression_verified', 'challenge_verified')
        rules = frozen['rules']
    else:
        cohorts = ('validation_verified',)
        args.output.mkdir(exist_ok=False)
    banks = fit_bank(model)
    for name in cohorts:
        decisions, pairs, features, sources = candidates_for(name, model, banks)
        if not args.regressions:
            rules = select(decisions, pairs, features)
        result = replay(decisions, pairs, features, rules)
        report = {'purpose': 'previously_inspected_development_regression', 'identity': identity,
                  'source_artifacts_sha256': sources, 'rules': rules, 'candidate_pairs': len(pairs),
                  'prior_metrics': metrics(decisions), 'metrics': metrics(result), 'decisions': result}
        with (args.output / (name + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
        print(name, rules, report['metrics'], flush=True)


if __name__ == '__main__':
    main()
