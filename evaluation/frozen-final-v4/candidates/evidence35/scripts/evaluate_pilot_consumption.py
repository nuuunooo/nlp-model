"""Compare the archived v4 workflow and its consumption add-on on a frozen batch."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

from recover_corroborated_recall import (
    ARTIFACT, MODEL, ROOT, WORKSPACE, FrozenEncoderScorer, additional_proofs, digest,
    eligible, incident_spans, inference_inputs, load, metrics, normalize, verify_breach,
)
from recover_pilot_recall import apply_rules, scoring_identity
from candidates.description34.src import engine as strict
from candidates.description34.src import setfit_classifier as setfit
from src.liquor_consumption import POLICY_FILE, consumption_evidence, load_consumption_policy


def frozen_engine():
    runtime = WORKSPACE / "evaluation/frozen-33/runtime"
    manifest = load(runtime.parent / "manifest.json")
    for path, expected in manifest["source_sha256"].items():
        if digest(runtime / path) != expected:
            raise ValueError(f"Frozen baseline source changed: {path}")
    for path, key in (("model.safetensors", "model_sha256"), ("model_head.pkl", "head_sha256"),
                      ("thresholds.json", "thresholds_sha256")):
        if digest(MODEL / path) != manifest["model_provenance"][key]:
            raise ValueError(f"Frozen category model changed: {path}")
    source = runtime / "src"
    spec = importlib.util.spec_from_file_location(
        "_consumption_frozen33", source / "__init__.py", submodule_search_locations=[str(source)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    from _consumption_frozen33 import engine, setfit_classifier
    return engine, setfit_classifier


class PilotReplay:
    def __init__(self):
        evaluation = ROOT / "evaluation"
        self.strict_report = load(WORKSPACE / "evaluation/candidate34/validation_verified.json")
        self.v2 = load(evaluation / "operational-evidence-recall-v2/validation_verified.json")
        self.v4 = load(evaluation / "operational-evidence-recall-v4/validation_verified.json")
        if self.v2["scoring_identity"] != scoring_identity():
            raise ValueError("v2 evidence scoring changed")
        for path, expected in self.v4["scoring_identity"].items():
            if digest(ROOT / path) != expected:
                raise ValueError(f"v4 evidence scoring changed: {path}")
        for path, expected in self.strict_report["source_sha256"].items():
            if digest(WORKSPACE / "candidates/description34" / path) != expected:
                raise ValueError(f"Strict baseline source changed: {path}")
        if digest(ARTIFACT / "metadata.json") != self.v4["verifier_sha256"]:
            raise ValueError("v4 evidence head changed")
        self.baseline, self.baseline_setfit = frozen_engine()
        self.taxonomy, self.lexicon = strict.catalog()
        self.classifier = setfit.SetFitClassifier(MODEL, self.taxonomy)
        self.codes = self.classifier.model.labels
        self.thresholds = np.array([self.classifier.thresholds[code] for code in self.codes])
        self.verifier = FrozenEncoderScorer(ARTIFACT, MODEL)

    def predict(self, descriptions, cached=None):
        groups = [inference_inputs(text, normalize) for text in descriptions]
        if cached is None:
            contexts = list(dict.fromkeys(text for group in groups for text in group))
            cached = dict(zip(contexts, setfit.score_codes(self.classifier.model, contexts), strict=True))

        def cached_scores(model, texts):
            return np.stack([cached[text] for text in texts])

        fallback = self.baseline_setfit.SetFitClassifier.__new__(self.baseline_setfit.SetFitClassifier)
        fallback.model, fallback.thresholds = self.classifier.model, self.classifier.thresholds
        baseline_tax, baseline_lex = self.baseline.catalog()
        records = [{"ticket_id": i + 1, "description": text} for i, text in enumerate(descriptions)]
        with (patch.object(setfit, "score_codes", side_effect=cached_scores),
              patch.object(self.baseline_setfit, "score_codes", side_effect=cached_scores)):
            findings = [{hit["code"] for hit in strict.analyze_ticket(
                row, self.taxonomy, self.lexicon, self.classifier)[1]} for row in records]
            agreed = [{hit["code"] for hit in self.baseline.analyze_ticket(
                row, baseline_tax, baseline_lex, fallback)[1]} for row in records]
        incidents = [[unit for unit in incident_spans(text, normalize) if not unit.blocked and not unit.is_requirement]
                     for text in descriptions]
        placements = [(index, unit, position) for index, units in enumerate(incidents) for unit in units
                      for position, code in enumerate(self.codes) if code not in findings[index] and eligible(code, unit)]
        keys = list(dict.fromkeys((unit.context, self.codes[position]) for _, unit, position in placements))
        scores = self.verifier.score_many([{"description": text, "target_code": code} for text, code in keys])
        support = {key: score[0] for key, score in zip(keys, scores, strict=True)}

        pairs = []
        v4_pairs = []
        for index, unit, position in placements:
            code = self.codes[position]
            evidence = float(support[unit.context, code])
            threshold = self.thresholds[position]
            local = cached[unit.context]
            ratio = float(local[position] / threshold)
            if evidence >= self.verifier.cutoff and any(cached[text][position] >= threshold for text in groups[index]):
                findings[index].add(code)
            if ratio >= .25:
                pairs.append((index, code, ratio, bool(verify_breach(code, unit)),
                              lead(local / self.thresholds, position), evidence))
            v4_pairs.append((index, code, ratio, float(local[position]), lead(local, position), evidence))
        v2 = apply_rules([{"predicted_codes": sorted(codes)} for codes in findings],
                         [pair for pair in pairs if pair[1] not in findings[pair[0]]], self.v2["rules"])
        final = [set(row["predicted_codes"]) for row in v2]
        explicit = {rule["category"] for rule in self.v4["rules"] if rule["method"] == "explicit"}
        for index, units in enumerate(incidents):
            final[index].update(code for unit in units for code in additional_proofs(unit) if code in explicit)
        for index, code, ratio, score, margin, evidence in v4_pairs:
            for rule in self.v4["rules"]:
                if (rule["method"] in ("local", "agreement")
                        and (rule["method"] == "local" or code in agreed[index])
                        and ratio >= rule["ratio"] and score >= rule["score"]
                        and margin >= rule["lead"] and evidence >= rule["support"]):
                    final[index].add(code)
        return final

    def verify_replay(self):
        strict_rows = self.strict_report["decisions"]
        first = load(ROOT / "evaluation/operational-evidence-pilot/validation_verified.json")["decisions"]
        v2, v4 = self.v2["decisions"], self.v4["decisions"]
        indices = {0, 100, 200, 700, 800}
        for older, newer in ((strict_rows, first), (first, v2), (v2, v4)):
            indices.update([i for i, (a, b) in enumerate(zip(older, newer, strict=True))
                            if a["predicted_codes"] != b["predicted_codes"]][:10])
        indices = sorted(indices)
        cache = WORKSPACE / "evaluation/candidate34/validation_final_scores.npz"
        expected = self.v4["source_artifacts_sha256"][cache.relative_to(WORKSPACE).as_posix()]
        if digest(cache) != expected:
            raise ValueError("Archived category scores changed")
        with np.load(cache, allow_pickle=False) as data:
            scores = dict(zip(data["texts"], data["scores"], strict=True))
        actual = self.predict([strict_rows[i]["description"] for i in indices], scores)
        if actual != [set(v4[i]["predicted_codes"]) for i in indices]:
            raise ValueError("Could not reproduce archived v4 decisions")
        return len(indices)


def lead(scores, position):
    if position != int(np.argmax(scores)):
        return -1.
    return float(scores[position] - np.max(np.delete(scores, position)))


def score_group(records, key):
    entries = [{"expected_decision": row["expected_decision"],
                "expected_codes": None if row["expected_decision"] == "abstain" else
                ["Liquor"] if row["expected_decision"] == "accept" else [],
                "predicted_codes": row[key]} for row in records]
    result = metrics(entries)
    if result["true_positives"] + result["false_positives"] == 0:
        result["precision"] = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--batch-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if digest(args.batch) != args.batch_sha256.lower():
        raise ValueError("Consumption batch changed after labeling")
    rows = load(args.batch)["records"]
    descriptions = [row["description"] for row in rows]
    pilot = PilotReplay()
    reproduced = pilot.verify_replay()
    base = pilot.predict(descriptions)
    policy = load_consumption_policy()
    records = []
    for row, old in zip(rows, base, strict=True):
        evidence = list(dict.fromkeys(consumption_evidence(row["description"], normalize, policy)))
        predictions = sorted(old | ({"Liquor"} if evidence else set()))
        records.append({**row, "v4_codes": sorted(old), "with_consumption_codes": predictions,
                        "consumption_evidence": evidence})
    cohorts = {"known": records[:3], "fresh": records[3:]}
    report = {
        "purpose": "Offline synthetic consumption comparison, separate from the sale checks.",
        "batch_sha256": args.batch_sha256.lower(), "policy_sha256": digest(POLICY_FILE),
        "source_sha256": {path.name: digest(path) for path in
                          (Path(__file__), ROOT / "src/liquor_consumption.py")},
        "v4_archive_checks": reproduced,
        "cohorts": {name: {key: score_group(group, key) for key in ("v4_codes", "with_consumption_codes")}
                    for name, group in cohorts.items()},
        "records": records,
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps(report["cohorts"], indent=2))


if __name__ == "__main__":
    main()
