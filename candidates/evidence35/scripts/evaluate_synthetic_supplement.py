"""Refit the v4 evidence head offline and replay the archived decision rules."""

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import recover_corroborated_recall as v4
import recover_pilot_recall as v2
from evaluate_pipeline_verifier import SetFitClassifier, catalog, metrics
from train_evidence_verifier import STATES, features, operational_examples, weights_for
from train_evidence_verifier import metrics as evidence_metrics


ROOT = v4.ROOT
MODEL = v4.MODEL
BASE = v4.ARTIFACT
DATA = ROOT / "data/evidence-v2"
V4_REPORTS = ROOT / "evaluation/operational-evidence-recall-v4"
WEIGHT_CAP = .25
# Quarantine complete matched groups when the spot review finds a material gap.
EXCLUSIONS = {
    "missing attributable vendor duty or breach": [
        16, 17, 18, 40, 41, 42, 62, 175, 176, 177, 194, 195, 197, 203, 204,
        283, 284, 285, 295, 296, 297, 298, 299, 300, 305, 306, 328, 330,
    ],
    "category unsupported by the note": [
        220, 221, 222, 256, 257, 258, 265, 266, 267, 346, 347, 348, 358, 359, 360,
        394, 395, 396, 400, 401, 402, 433, 434, 435, 439, 440, 441, 445, 446, 447,
        451, 452, 453, 514, 515, 516,
    ],
    "insufficient evidence of intentional interference": [
        392, 393, 403, 404, 405, 472, 473, 474, 502, 503, 504,
    ],
}
REPAIRED_GROUPS = {16, 17, 18, 394, 395, 396, 400, 401, 402, 403, 404, 405}
REVISED_EXCLUSIONS = {
    543: "applicable buyer age rule missing from the liquor evidence",
    564: "verified amount paid missing from the price evidence",
    570: "applicable supplier-log requirement missing",
    587: "vendor control of the supplier's obstruction is unverified",
    598: "date on the product is not identified as expiry",
    604: "applicable unloading restriction missing",
    605: "applicable unloading restriction missing",
    610: "presence of vehicle does not establish delivery under the stated rule",
    633: "wristband sales do not verify attendance",
}
RECOVERY_CODES = frozenset({
    "Lighting & Energy", "Bladed Instruments", "Liquor", "Price Monitoring", "Market Rules",
    "Obstruction", "Sanitation", "Traffic", "Porter Regulation", "Entertainment Activities",
})


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def supplement(path, codes, old_texts, evaluation_texts, previous_feed=None):
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    records, groups, headings = defaultdict(list), defaultdict(list), defaultdict(set)
    for row in rows:
        records[row["record_id"]].append(row)
        groups[row["group_id"]].append(row)
        headings[row["source_category"]].add(row["scenario_type"])
        if (None in row or not all(row.values()) or row["source_type"] != "synthetic"
                or row["category"] not in codes or row["evidence_state"] not in STATES
                or row["language"] not in {"en", "fil", "taglish"}
                or row["evidence_quote"] not in row["description"]
                or not 0 < len(row["description"]) <= 120
                or len(row["description"].splitlines()) != 1):
            raise ValueError(f"Invalid synthetic incident row: {row['record_id']}")
    for record, items in records.items():
        if len(items) not in (1, 2) or {(r["check_role"], r["incident_id"]) for r in items} != (
                {("primary", "1")} if len(items) == 1 else {("primary", "1"), ("secondary", "2")}):
            raise ValueError(f"Invalid incident layout: {record}")
        for key in ("description", "group_id", "source_category", "scenario_type", "language"):
            if len({r[key] for r in items}) != 1:
                raise ValueError(f"Inconsistent record {record}: {key}")
        if len({r["category"] for r in items}) != len(items):
            raise ValueError(f"Repeated category for record {record}")
    excluded = {f"G{number:03}": reason for reason, numbers in EXCLUSIONS.items() for number in numbers}
    revised_audit = None
    if previous_feed is not None:
        with previous_feed.open(encoding="utf-8-sig", newline="") as source:
            previous = {(r["record_id"], r["incident_id"]): r for r in csv.DictReader(source)}
        present = {(r["record_id"], r["incident_id"]): r for r in rows}
        if len(present) != len(rows) or not previous.keys() <= present.keys():
            raise ValueError("Revised feed lost original incident IDs or has duplicate keys")
        additions = [r for key, r in present.items() if key not in previous]
        changed_notes = {r["record_id"] for key, r in previous.items()
                         if r["description"] != present[key]["description"]}
        changed_groups = {r["group_id"] for r in rows if r["record_id"] in changed_notes}
        repaired = {f"G{n:03}" for n in REPAIRED_GROUPS}
        if not repaired <= excluded.keys() & changed_groups:
            raise ValueError("Reviewed repairs do not match the original and revised feeds")
        excluded = {group: reason for group, reason in excluded.items() if group not in repaired}
        excluded.update({f"G{n:03}": reason for n, reason in REVISED_EXCLUSIONS.items()})
        revised_audit = {
            "previous_feed_sha256": v4.digest(previous_feed), "new_rows": len(additions),
            "new_descriptions": len({r["record_id"] for r in additions}),
            "changed_original_descriptions": len(changed_notes),
            "restored_reviewed_groups": sorted(repaired),
        }
    if not excluded.keys() <= groups.keys():
        raise ValueError("Spot review group IDs do not match the supplied feed")
    # Split by scenario type, keeping its three languages and all outcomes together.
    holdout = {
        (heading, context)
        for heading, contexts in headings.items()
        for context in sorted(contexts, key=lambda text: sha256(f"42:{heading}:{text}".encode()).digest())
        [:max(1, round(len(contexts) * .2))]
    }
    fit, held, full_context = [], [], set()
    for group, items in groups.items():
        primaries = [r for r in items if r["check_role"] == "primary"]
        identities = {(r["source_category"], r["scenario_type"], r["language"], r["category"]) for r in primaries}
        if (len(primaries) != 3 or len(identities) != 1
                or {r["evidence_state"] for r in primaries} != set(STATES)):
            raise ValueError(f"Invalid matched scenario group: {group}")
        heading, context, _, _ = identities.pop()
        if group in excluded:
            continue
        pairs = []
        for row in items:
            # In a mixed note, train on the local evidence for the nominated category.
            raw = row["description"] if len(records[row["record_id"]]) == 1 else row["evidence_quote"]
            text = v4.normalize(raw)
            if text in evaluation_texts or v4.normalize(row["description"]) in evaluation_texts:
                excluded[group] = "exact normalized overlap with an archived evaluation"
                break
            pairs.append({
                "description": text, "target_code": row["category"], "evidence_state": row["evidence_state"],
                "kind": "synthetic_supplement", "family_ids": [heading, context, row["category"]],
                "record_id": row["record_id"], "group_id": group, "language": row["language"],
            })
        else:
            if (heading, context) in holdout:
                if any(row["description"] in old_texts for row in pairs):
                    excluded[group] = "held-out incident overlaps prior fit data"
                    continue
                held.extend(pairs)
            else:
                fit.extend(pairs)
                full_context.update(v4.normalize(row["description"]) for row in items)
    fit_texts = {r["description"] for r in fit} | full_context
    overlapping = {r["group_id"] for r in held if r["description"] in fit_texts}
    excluded.update({group: "held-out incident overlaps supplement fit text" for group in overlapping})
    held = [r for r in held if r["group_id"] not in overlapping]
    # Omit repeated pairs and any contradictory same-text/category targets in the supplement.
    states = defaultdict(set)
    for row in fit:
        states[row["description"], row["target_code"]].add(row["evidence_state"])
    conflicts = {key for key, values in states.items() if len(values) > 1}
    unique_fit = {}
    for row in fit:
        key = (row["description"], row["target_code"])
        if key not in conflicts:
            unique_fit.setdefault(key, row)
    audit = {
        "source_sha256": v4.digest(path), "rows": len(rows), "descriptions": len(records),
        "groups": len(groups), "contexts": sum(map(len, headings.values())),
        "mixed_descriptions": sum(len(items) == 2 for items in records.values()),
        "max_description_length": max(len(r["description"]) for r in rows),
        "excluded_groups": excluded, "fit_duplicate_or_conflicting_rows": len(fit) - len(unique_fit),
        "fit_contexts": sorted({tuple(r["family_ids"][:2]) for r in unique_fit.values()}),
        "held_out_contexts": sorted({tuple(r["family_ids"][:2]) for r in held}),
        "fit_record_ids": sorted({r["record_id"] for r in unique_fit.values()}),
        "held_out_record_ids": sorted({r["record_id"] for r in held}),
        "fit_counts": dict(Counter(r["evidence_state"] for r in unique_fit.values())),
        "holdout_counts": dict(Counter(r["evidence_state"] for r in held)),
        "revision": revised_audit,
    }
    return list(unique_fit.values()), held, audit


def replay_inputs(name):
    references, _, old, codes, scores, thresholds, identity = v4.sources(name)
    archived = v4.load(V4_REPORTS / (name + ".json"))
    if archived["source_artifacts_sha256"] != identity:
        raise ValueError(f"Archived v4 inputs changed: {name}")
    prior_rules = v4.load(v4.REPLAY / (name + ".json"))["rules"]
    bases, first, second, last, explicit = [], [], [], [], []
    limits = np.array([thresholds[code] for code in codes])
    for i, (row, baseline) in enumerate(zip(references, old)):
        bases.append({k: row[k] for k in ("scenario_id", "expected_codes", "expected_decision", "predicted_codes")})
        existing = set(row["predicted_codes"])
        agreed = set(baseline["predicted_codes"])
        nominated = np.any(
            [scores[value] >= limits for value in v4.inference_inputs(row["description"], v4.normalize)], axis=0
        )
        for unit in v4.incident_spans(row["description"], v4.normalize):
            if unit.blocked or unit.is_requirement:
                continue
            explicit.extend((i, code) for code in v4.additional_proofs(unit) if code not in existing)
            values = scores[unit.context]
            ratios = values / limits
            ratio_leader, score_leader = int(np.argmax(ratios)), int(np.argmax(values))
            ratio_lead = float(ratios[ratio_leader] - np.delete(ratios, ratio_leader).max())
            score_lead = float(values[score_leader] - np.delete(values, score_leader).max())
            for pos, code in enumerate(codes):
                if code in existing or not v4.eligible(code, unit):
                    continue
                key = (unit.context, code)
                if nominated[pos]:
                    first.append((i, code, key))
                proof = bool(v4.verify_breach(code, unit))
                if ratios[pos] >= min(v2.NOMINATION_RATIOS):
                    second.append((i, code, float(ratios[pos]), proof,
                                   ratio_lead if pos == ratio_leader else -1., key))
                if values[pos] >= min(v4.PROBABILITIES):
                    last.append((i, code, float(values[pos]), score_lead if pos == score_leader else -1.,
                                 float(ratios[pos]), code in agreed, proof, key))
    keys = list(dict.fromkeys(entry[-1] for layer in (first, second, last) for entry in layer))
    return bases, first, second, last, sorted(set(explicit)), keys, prior_rules, archived


def run_replay(inputs, support, cutoff):
    bases, first, second, last, explicit, _, prior_rules, archived = inputs
    findings = [set(row["predicted_codes"]) for row in bases]
    if cutoff is not None:
        for i, code, key in first:
            if support[key] >= cutoff:
                findings[i].add(code)
    decisions = [dict(row, predicted_codes=sorted(codes)) for row, codes in zip(bases, findings)]
    second_pairs = [(*item[:-1], support[item[-1]]) for item in second]
    decisions = v2.apply_rules(decisions, second_pairs, prior_rules)
    signals = {
        "support": [support[r[-1]] for r in last], "score": [r[2] for r in last],
        "lead": [r[3] for r in last], "ratio": [r[4] for r in last],
        "agreement": [r[5] for r in last], "proof": [r[6] for r in last],
    }
    for key, values in signals.items():
        dtype = bool if key in ("agreement", "proof") else float
        signals[key] = np.array(values + [0] * len(explicit), dtype=dtype)
    pairs = [(r[0], r[1]) for r in last] + explicit
    signals["explicit"] = np.array([False] * len(last) + [True] * len(explicit))
    signals["code"] = np.array([code for _, code in pairs], dtype=str)
    return v4.replay(decisions, pairs, signals, archived["rules"])


def recovery_options(inputs, support):
    archived = inputs[-1]["decisions"]
    existing = [set(row["predicted_codes"]) for row in archived]
    options = {"proof": [], "agreement": []}
    for i, code, ratio, proof, _, key in inputs[2]:
        if proof and code in RECOVERY_CODES and code not in existing[i]:
            options["proof"].append((i, code, ratio, support[key]))
    for i, code, score, lead, ratio, agrees, _, key in inputs[3]:
        if (agrees and score >= .75 and lead >= .20 and ratio >= 1.
                and code in RECOVERY_CODES and code not in existing[i]):
            options["agreement"].append((i, code, ratio, support[key]))
    return options


def recover(options, rules):
    return {(i, code) for method, ratio, cutoff in rules for i, code, category_ratio, support in options[method]
            if category_ratio >= ratio and support >= cutoff}


def select_recovery_rules(inputs, support):
    baseline = inputs[-1]["decisions"]
    options = recovery_options(inputs, support)
    allowed = {(i, code) for i, row in enumerate(baseline) if row["expected_decision"] == "accept"
               for code in (row["expected_codes"] or ())}
    rules, already = [], set()
    for method, ratios in (("proof", (.5, .75, 1.)), ("agreement", (1.,))):
        best = None
        for ratio, cutoff in product(ratios, v4.SUPPORT):
            rule = (method, ratio, cutoff)
            additions = recover(options, [rule]) - already
            scenarios = {baseline[i]["scenario_id"] for i, _ in additions}
            if len(additions) < 4 or len(scenarios) < 2 or not additions <= allowed:
                continue
            rank = (len(additions), len(scenarios), ratio, cutoff)
            if best is None or rank > best[0]:
                best = rank, rule, additions
        if best is not None:
            _, rule, additions = best
            rules.append(rule)
            already.update(additions)
    return rules


def run_additive_replay(inputs, support, rules):
    archived = inputs[-1]["decisions"]
    accepted = [set(row["predicted_codes"]) for row in archived]
    for index, code in recover(recovery_options(inputs, support), rules):
        accepted[index].add(code)
    return [dict(row, predicted_codes=sorted(codes)) for row, codes in zip(archived, accepted)]


def select_cutoff(rows, probabilities):
    supported = np.array([row["evidence_state"] == "supported" for row in rows])
    compliant = np.array([row["evidence_state"] == "compliant" for row in rows])
    best = (0, 0, 0.)
    for value in np.unique(probabilities[:, 0]):
        accepted = probabilities[:, 0] >= value
        tp = int(np.sum(accepted & supported))
        fp = int(np.sum(accepted & ~supported))
        if tp and tp / (tp + fp) >= .98 and not np.any(accepted & compliant):
            best = max(best, (tp, -fp, float(value)))
    return best[2] if best[0] else None


def by_category(decisions, codes):
    output = {}
    for code in codes:
        expected = {i for i, row in enumerate(decisions) if code in (row["expected_codes"] or ())}
        predicted = {i for i, row in enumerate(decisions)
                     if row["expected_codes"] is not None and code in row["predicted_codes"]}
        output[code] = dict(expected=len(expected), correct=len(expected & predicted), extra=len(predicted - expected))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--calibrate-weights", action="store_true",
                        help="Select supplement weight against the original validation gates")
    parser.add_argument("--previous-feed", type=Path,
                        help="Audit the revised feed against its predecessor and test additive recovery")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    taxonomy, _ = catalog()
    codes = list(taxonomy)
    metadata = v4.load(BASE / "metadata.json")
    if metadata["codes"] != codes or v4.digest(BASE / "head.joblib") != metadata["head_sha256"]:
        raise ValueError("Original verifier identity changed")
    for name, expected in metadata["encoder_identity"].items():
        if v4.digest(MODEL / name) != expected:
            raise ValueError(f"Frozen encoder file changed: {name}")
    for name, expected in metadata["data_sha256"].items():
        if v4.digest(DATA / name) != expected:
            raise ValueError(f"Original verifier training source changed: {name}")
    fit, validation = (read_jsonl(DATA / f"{split}.jsonl") for split in ("fit", "validation"))
    for row in fit + validation:
        row["description"] = v4.normalize(row["description"])
    labels = {c: v4.normalize(c + ". " + taxonomy[c]["evidence_requirement_en"]) for c in codes}
    cached_texts = list(dict.fromkeys([r["description"] for r in fit + validation] + list(labels.values())))
    identity = {
        "encoder_sha256": metadata["encoder_identity"],
        "input_sha256": sha256(json.dumps(cached_texts, ensure_ascii=False).encode()).hexdigest(),
        "normalizer_sha256": v4.digest(ROOT / "src/engine.py"),
    }
    with np.load(ROOT / "evaluation/evidence_embeddings_v1.npz", allow_pickle=False) as cache:
        if json.loads(str(cache["provenance"])) != identity:
            raise ValueError("Original verifier embedding provenance changed")
        vectors = dict(zip(cached_texts, cache["embeddings"]))
        lengths = dict(zip(cached_texts, cache["lengths"]))
    legacy, provenance = operational_examples(
        ROOT / "data/operational-development/operational_development.csv", validation, codes
    )
    if provenance != metadata["operational_fit_only"]:
        raise ValueError("Original verifier supplemental data changed")
    fit.extend(legacy)
    replays = {name: replay_inputs(name) for name in v4.COHORTS}
    evaluation_texts = {r["description"] for r in validation} | {
        value for name in replays for row in v4.sources(name)[0]
        for value in v4.inference_inputs(row["description"], v4.normalize)
    }
    new, held, audit = supplement(args.feed, codes, {r["description"] for r in fit}, evaluation_texts,
                                  args.previous_feed)
    (args.output / "feed_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Audited feed: {len(new)} fit pairs, {len(held)} held-out pairs, "
          f"{len(audit['excluded_groups'])} quarantined groups", flush=True)
    needed = list(dict.fromkeys(
        [r["description"] for r in fit + new + held] +
        [text for inputs in replays.values() for text, _ in inputs[5]]
    ))
    missing = [text for text in needed if text not in vectors]
    body = SetFitClassifier(MODEL, taxonomy).model.model_body
    queries = ["query: " + text for text in missing]
    lengths.update(zip(missing, map(len, body.tokenizer(queries, truncation=False, padding=False)["input_ids"])))
    valid = [text for text in missing if lengths[text] <= body.max_seq_length]
    print(f"Encoding {len(valid)} new fit, holdout, and regression texts on CPU", flush=True)
    for start in range(0, len(valid), 64):
        batch = valid[start:start + 64]
        embedded = body.encode(["query: " + text for text in batch], batch_size=32,
                               normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
        vectors.update(zip(batch, embedded))
        if start % 256 == 0 or start + 64 >= len(valid):
            print(f"Encoded {start + len(batch)}/{len(valid)}", flush=True)
    del body
    category_vectors = {code: np.asarray(vec, dtype=np.float32) for code, vec in metadata["category_vectors"].items()}

    def predict(model, rows):
        available = [i for i, row in enumerate(rows) if row["description"] in vectors
                     and lengths[row["description"]] <= metadata["max_sequence_length"]]
        output = np.zeros((len(rows), 3))
        output[:, 2] = 1.
        if available:
            output[available] = model.predict_proba(
                features([rows[i] for i in available], vectors, category_vectors, codes)
            )
        return output

    old_head = joblib.load(BASE / "head.joblib")
    old_validation = predict(old_head, validation)
    with np.load(BASE / "validation_probabilities.npz", allow_pickle=False) as cache:
        if not np.allclose(old_validation, cache["probabilities"], atol=1e-6):
            raise ValueError("Original verifier validation scores did not reproduce")
    combined = [r for r in fit + new if lengths[r["description"]] <= metadata["max_sequence_length"]]
    targets = np.array([STATES.index(r["evidence_state"]) for r in combined])
    base_weights = weights_for(combined)
    added = np.array([r["kind"] == "synthetic_supplement" for r in combined])
    old_cutoff = metadata["supported_cutoff"]
    val_inputs = replays["validation_verified"]
    val_keys = val_inputs[5]
    val_pairs = [{"description": text, "target_code": code} for text, code in val_keys]
    validation_before = val_inputs[-1]["metrics"]
    fit_features = features(combined, vectors, category_vectors, codes)
    selections = []
    selected = None
    weight_caps = (.005, .01, .025, .05, .10, .175, WEIGHT_CAP) if args.calibrate_weights else (WEIGHT_CAP,)
    print(f"Fitting the same verifier recipe on {len(combined)} pairs", flush=True)
    for cap in weight_caps:
        weights = base_weights.copy()
        for target in range(len(STATES)):
            state = targets == target
            original_weight = weights[state & ~added].sum()
            added_weight = weights[state & added].sum()
            weights[state & added] *= min(1., original_weight * cap / (1 - cap) / added_weight)
            total = int((~added).sum()) if args.calibrate_weights else len(combined)
            weights[state] *= total / 3 / weights[state].sum()
        head = make_pipeline(StandardScaler(), LogisticRegression(C=4, max_iter=1000, random_state=42))
        head.fit(fit_features, targets, standardscaler__sample_weight=weights, logisticregression__sample_weight=weights)
        probabilities = predict(head, validation)
        cutoff = select_cutoff(validation, probabilities)
        scores = dict(zip(val_keys, predict(head, val_pairs)[:, 0]))
        result = metrics(run_replay(val_inputs, scores, cutoff))
        passed = (cutoff is not None and result["false_positives"] <= validation_before["false_positives"]
                  and result["multi_exact"] >= validation_before["multi_exact"]
                  and result["true_positives"] >= validation_before["true_positives"]
                  and not result["clear_false_actions"] and not result["unclear_false_actions"])
        entry = {"weight_cap": cap, "cutoff": cutoff, "validation_pipeline": result,
                 "validation_evidence": evidence_metrics(validation, probabilities, cutoff),
                 "validation_gate_passed": passed}
        selections.append(entry)
        print(f"Validation cap={cap}: cutoff={cutoff}, gate={passed}, pipeline={result}", flush=True)
        rank = (passed, cutoff is not None, result["true_positives"], result["multi_exact"], -result["false_positives"], -cap)
        if selected is None or rank > selected[0]:
            selected = rank, cap, head, weights, cutoff
    _, cap, head, weights, cutoff = selected
    print(f"Support cutoff: original={old_cutoff}, refit={cutoff}", flush=True)
    summary = {
        "comparison": "Frozen strict findings, v2 recovery rules, v4 recovery rules and category model. "
                      "Refit evidence head and recalibrate its first-stage cutoff on legacy validation only.",
        "fit_pairs": len(combined), "supplement_fit_pairs": int(added.sum()),
        "holdout_pairs": len(held), "holdout_is_author_labeled_synthetic": True,
        "maximum_supplement_weight_per_state": cap,
        "weight_calibration": selections,
        "actual_supplement_weight_per_state": {
            state: float(weights[(targets == i) & added].sum() / weights[targets == i].sum())
            for i, state in enumerate(STATES)
        },
        "old_cutoff": old_cutoff, "new_cutoff": cutoff,
        "validation_evidence": {
            "before": evidence_metrics(validation, old_validation, old_cutoff),
            "after": evidence_metrics(validation, predict(head, validation), cutoff),
        },
        "held_out_evidence": {
            "before": evidence_metrics(held, predict(old_head, held), old_cutoff),
            "after": evidence_metrics(held, predict(head, held), cutoff),
        },
        "cohorts": {},
    }
    if args.previous_feed is not None:
        new_rules = select_recovery_rules(val_inputs, dict(zip(val_keys, predict(head, val_pairs)[:, 0])))
        old_rules = select_recovery_rules(val_inputs, dict(zip(val_keys, predict(old_head, val_pairs)[:, 0])))
        summary["additive"] = {"revised_head_rules": new_rules, "original_head_control_rules": old_rules}
        print(f"Validation-only additive rules: revised={new_rules}, original control={old_rules}", flush=True)
    for name, inputs in replays.items():
        keys = inputs[5]
        rows = [{"description": text, "target_code": code} for text, code in keys]
        original_scores = dict(zip(keys, predict(old_head, rows)[:, 0]))
        revised_scores = dict(zip(keys, predict(head, rows)[:, 0]))
        before = run_replay(inputs, original_scores, old_cutoff)
        if before != inputs[-1]["decisions"]:
            raise ValueError(f"Original v4 decisions failed to reproduce on {name}")
        after = run_replay(inputs, revised_scores, cutoff)
        change = {"before": metrics(before), "after": metrics(after),
                  "before_by_category": by_category(before, codes), "after_by_category": by_category(after, codes)}
        summary["cohorts"][name] = change
        if args.previous_feed is not None:
            additive = run_additive_replay(inputs, revised_scores, new_rules)
            control = run_additive_replay(inputs, original_scores, old_rules)
            change.update(additive=metrics(additive), additive_control=metrics(control),
                          additive_by_category=by_category(additive, codes))
            (args.output / (name + "_additive.json")).write_text(
                json.dumps({"revised_head": additive, "original_head_control": control}, indent=2), encoding="utf-8"
            )
            print(name, "additive", change["additive"], "control", change["additive_control"], flush=True)
        (args.output / (name + ".json")).write_text(
            json.dumps(dict(change, decisions=after), indent=2), encoding="utf-8"
        )
        print(name, change["after"], flush=True)
    model_path = args.output / "head.joblib"
    joblib.dump(head, model_path)
    candidate_metadata = dict(
        metadata, fit_rows=len(combined), head_sha256=v4.digest(model_path), supported_cutoff=cutoff,
        selection_feasible=cutoff is not None, release_qualified=False,
        training_code_sha256=v4.digest(Path(__file__)), supplement_sha256=audit["source_sha256"],
        validation=summary["validation_evidence"]["after"],
    )
    candidate_metadata.pop("validation_by_kind", None)
    (args.output / "metadata.json").write_text(json.dumps(candidate_metadata, indent=2), encoding="utf-8")
    (args.output / "performance.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
