"""Trace a frozen CSV evaluation and run a description-only segmentation experiment.

This script never changes rules, weights, thresholds, gold labels, or baseline output.
Its experimental results are development diagnostics, not another untouched test.
"""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import engine
from src.description_evidence import (
    COMPLIANT_CATEGORY, INCIDENT_SEPARATOR, UNCERTAIN_NOTE,
    described_weight_outcome, followed_by_unconfirmed_statement, supports_category,
)
from src.setfit_classifier import SetFitClassifier, score_codes


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def evidence_checks(code, text):
    """Mirror the existing engine's model gate, retaining all blocker reasons."""
    if code == "WeightMeasures":
        outcome, reason, _ = described_weight_outcome(text)
        return {"supported": outcome == "violation", "weight_outcome": outcome,
                "weight_reason": reason}
    statements = re.split(r"(?<=[.!?])\s+", text)
    checks = []
    for index, clause in enumerate(statements):
        blockers = []
        if "?" in clause:
            blockers.append("question")
        if engine.AMBIGUOUS_RE.search(clause) or UNCERTAIN_NOTE.search(clause):
            blockers.append("uncertainty_expression")
        if engine.CLEAN_RE.search(clause):
            blockers.append("explicit_clear_expression")
        if code in COMPLIANT_CATEGORY and COMPLIANT_CATEGORY[code].search(clause):
            blockers.append("compliance_expression")
        if not supports_category(code, clause):
            blockers.append("category_support_rejected")
        if followed_by_unconfirmed_statement(statements, index):
            blockers.append("unconfirmed_followup")
        checks.append({"statement_index": index, "blockers": blockers})
    return {"supported": any(not item["blockers"] for item in checks), "statements": checks}


def segments(text):
    # Preserve commas inside quantity comparisons. Split explicit incident connectors only.
    return [part.strip() for statement in INCIDENT_SEPARATOR.split(text)
            for part in re.split(r",\s*(?:also|tapos)\s+|\s+tapos\s+", statement, flags=re.I)
            if part.strip()]


def metrics(decisions):
    known = [d for d in decisions if d["expected_codes"] is not None]
    tp = sum(len(set(d["expected_codes"]) & set(d["predicted_codes"])) for d in known)
    fp = sum(len(set(d["predicted_codes"]) - set(d["expected_codes"])) for d in known)
    fn = sum(len(set(d["expected_codes"]) - set(d["predicted_codes"])) for d in known)
    multi = [d for d in known if len(d["expected_codes"]) > 1]
    return {"known_rows": len(known), "true_positives": tp, "false_positives": fp,
            "false_negatives": fn, "micro_precision": tp / (tp + fp) if tp + fp else 0,
            "micro_recall": tp / (tp + fn) if tp + fn else 0,
            "micro_f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0,
            "exact_label_set_matches": sum(set(d["expected_codes"]) == set(d["predicted_codes"]) for d in known),
            "multi_label_rows": len(multi),
            "multi_label_exact_matches": sum(set(d["expected_codes"]) == set(d["predicted_codes"]) for d in multi),
            "clear_rows_with_actions": sum(bool(d["predicted_codes"]) for d in decisions if d["expected_decision"] == "clear"),
            "abstain_rows_with_actions": sum(bool(d["predicted_codes"]) for d in decisions if d["expected_decision"] == "abstain")}


def diagnose(source, baseline_path, output_dir):
    import numpy as np

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if digest(source) != baseline["source_csv_sha256"]:
        raise ValueError("CSV changed since the baseline evaluation")
    frozen = baseline["source_sha256"]
    for name, expected_hash in frozen.items():
        if digest(name) != expected_hash:
            raise ValueError(f"Frozen runtime changed: {name}")
    model_dir = Path(baseline["model"])
    for name, key in (("model.safetensors", "model_sha256"), ("model_head.pkl", "head_sha256"),
                      ("thresholds.json", "thresholds_sha256")):
        if digest(model_dir / name) != baseline["provenance"][key]:
            raise ValueError(f"Frozen model artifact changed: {name}")
    rows = list(csv.DictReader(source.open(encoding="utf-8-sig", newline="")))
    original = {d["record_id"]: d for d in baseline["decisions"]}
    if len(original) != len(rows) or {r["record_id"] for r in rows} != set(original):
        raise ValueError("CSV records do not match the baseline")
    taxonomy, lexicon = engine.catalog()
    codes = baseline["provenance"]["codes"]
    thresholds = json.loads((model_dir / "thresholds.json").read_text(encoding="utf-8"))["thresholds"]
    parts = [segments(r["description"]) for r in rows]
    whole_texts = [engine.normalize(r["description"]) for r in rows]
    flat_parts = [engine.normalize(p) for group in parts for p in group]
    provenance = {"source_sha256": digest(source), "baseline_sha256": digest(baseline_path),
                  "runtime_sha256": frozen, "scorer_sha256": digest("src/setfit_classifier.py"),
                  "model": baseline["provenance"],
                  "input_sha256": sha256(json.dumps(whole_texts + flat_parts, ensure_ascii=False).encode()).hexdigest(),
                  "script_sha256": digest(__file__)}
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = output_dir / "diagnostic_scores.npz"
    if cache.exists():
        with np.load(cache, allow_pickle=False) as data:
            if json.loads(str(data["provenance"])) != provenance:
                raise ValueError("Diagnostic cache provenance mismatch")
            all_scores = data["scores"]
        from types import SimpleNamespace
        classifier = SetFitClassifier.__new__(SetFitClassifier)
        classifier.model = SimpleNamespace(labels=codes)
        classifier.thresholds = thresholds
    else:
        classifier = SetFitClassifier(model_dir, taxonomy)
        print(f"Scoring {len(rows)} whole descriptions and {len(flat_parts)} incident fragments.", flush=True)
        all_scores = score_codes(classifier.model, whole_texts + flat_parts)
        np.savez_compressed(cache, scores=all_scores, provenance=json.dumps(provenance))
    if all_scores.shape != (len(rows) + len(flat_parts), len(codes)) or not np.isfinite(all_scores).all():
        raise ValueError("Invalid diagnostic scores")

    def predict(text, scores, record_id):
        with patch("src.setfit_classifier.score_codes", return_value=scores[None, :]):
            _, findings = engine.analyze_ticket({"ticket_id": record_id, "description": text}, taxonomy, lexicon, classifier)
        return {finding["code"]: finding["source"] for finding in findings}

    missing = []
    false_actions = []
    diagnostics = []
    experimental = []
    source_counts = Counter()
    rescued = Counter()
    offset = len(rows)
    for i, row in enumerate(rows):
        record_id = row["record_id"]
        saved = original[record_id]
        gold = saved["expected_codes"]
        csv_gold = sorted(filter(None, row["gold_codes"].split("|"))) if row["expected_decision"] != "abstain" else None
        if csv_gold != (sorted(gold) if gold is not None else None) or row["expected_decision"] != saved["expected_decision"]:
            raise ValueError(f"Baseline gold labels changed: {record_id}")
        findings = predict(row["description"], all_scores[i], record_id)
        if set(findings) != set(saved["predicted_codes"]) or findings != saved["sources"]:
            raise ValueError(f"Frozen baseline replay mismatch: {record_id}")
        source_counts.update(findings.values())
        fragment_scores = all_scores[offset:offset + len(parts[i])]
        offset += len(parts[i])
        fragment_predictions = set()
        for p, scores in zip(parts[i], fragment_scores):
            fragment_predictions.update(predict(p, scores, record_id))
        union_predictions = sorted(set(findings) | fragment_predictions)
        experimental.append({"record_id": record_id, "expected_codes": gold,
                             "expected_decision": saved["expected_decision"], "predicted_codes": union_predictions})
        per_record = {"record_id": record_id, "expected_decision": saved["expected_decision"],
                      "expected_codes": gold, "baseline_codes": sorted(findings),
                      "experimental_union_codes": union_predictions, "segment_count": len(parts[i]),
                      "missing_codes": saved["missing_codes"], "false_action_codes": saved["unrelated_codes"]}
        diagnostics.append(per_record)
        for code in saved["missing_codes"]:
            column = codes.index(code)
            score = float(all_scores[i, column])
            gate = evidence_checks(code, whole_texts[i])
            if code == "WeightMeasures":
                cause = "weight_parser_did_not_establish_violation"
            elif score < thresholds[code]:
                cause = "below_threshold_only" if gate["supported"] else "below_threshold_and_evidence_gate"
            else:
                cause = "evidence_gate_only" if not gate["supported"] else "unexpected_trace_mismatch"
            recovered = code in union_predictions
            if recovered:
                rescued[cause] += 1
            missing.append({"record_id": record_id, "code": code, "cause": cause,
                            "whole_note_score": score, "threshold": thresholds[code],
                            "below_threshold": score < thresholds[code], "evidence_gate": gate,
                            "best_fragment_score": float(fragment_scores[:, column].max()),
                            "recovered_by_experimental_union": recovered})
        for code in saved["unrelated_codes"]:
            column = codes.index(code)
            false_actions.append({"record_id": record_id, "code": code, "source": findings[code],
                                  "expected_decision": saved["expected_decision"],
                                  "whole_note_score": float(all_scores[i, column]), "threshold": thresholds[code],
                                  "evidence_gate": evidence_checks(code, whole_texts[i])})
    if offset != len(all_scores):
        raise ValueError("Fragment score offsets do not reconcile")
    baseline_metrics = metrics(baseline["decisions"])
    assert baseline_metrics["false_negatives"] == len(missing)
    assert baseline_metrics["false_positives"] + baseline_metrics["abstain_rows_with_actions"] == len(false_actions)
    # Validate both runtime and all three model artifacts again after the experiment.
    for name, expected_hash in frozen.items():
        assert digest(name) == expected_hash, name
    for name, key in (("model.safetensors", "model_sha256"), ("model_head.pkl", "head_sha256"),
                      ("thresholds.json", "thresholds_sha256")):
        assert digest(model_dir / name) == baseline["provenance"][key], name
    assert digest(baseline_path) == provenance["baseline_sha256"]
    result = {
        "method": "Exact frozen baseline replay, per-label model/gate tracing, and one exploratory whole-note-plus-fragment union. Only descriptions enter inference; gold labels and label_evidence never do.",
        "limitations": ["Score/gate traces identify mechanical failure paths, not independent adjudication of gold labels.",
                        "The segmentation experiment uses this already inspected dataset and is development evidence only.",
                        "Fragmentation can remove context or qualifiers; this experiment is not a deployable replacement.",
                        "No thresholds, weights, rules, or gold labels were changed."],
        "provenance": provenance, "baseline_replayed_exactly": True, "frozen_artifacts_unchanged": True,
        "baseline_metrics": baseline_metrics, "baseline_finding_sources_all_150": dict(source_counts),
        "missing_gold_labels_by_path": dict(Counter(m["cause"] for m in missing)),
        "missing_gold_labels_below_threshold": sum(m["below_threshold"] for m in missing),
        "false_actions_by_source_including_abstain": dict(Counter(f["source"] for f in false_actions)),
        "experimental_union_metrics": metrics(experimental), "experimental_rescues_by_baseline_path": dict(rescued),
        "missing_gold_labels": missing, "false_actions": false_actions, "records": diagnostics,
    }
    output = output_dir / "diagnosis.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"provenance", "missing_gold_labels", "false_actions", "records"}}, indent=2), flush=True)
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("C:/Users/admin/Downloads/market_inspection_eval_multilabel.csv"))
    parser.add_argument("--baseline", type=Path, default=Path("evaluation/market-inspection-multilabel/evaluation.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/market-inspection-multilabel/diagnostic"))
    args = parser.parse_args()
    diagnose(args.csv, args.baseline, args.output_dir)
