"""Evaluate the six verified add-ons together over frozen original v4."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path

from evaluate_pilot_consumption import PilotReplay
from recover_corroborated_recall import ARTIFACT, COHORTS, ROOT, WORKSPACE, digest, load, metrics, normalize, sources
from src.targeted_v4 import CHECKS, with_targeted_v4


BASELINE = ROOT / "evaluation/operational-evidence-recall-v4"
HISTORICAL = "test_regression_verified"
BASELINE_COUNTS = (804, 555, 8, 261, 34, 60)


def compare(row, baseline):
    text = row["description"]
    original = frozenset(baseline)
    combined, checks = with_targeted_v4(text, original, normalize)
    ordered_predictions = []
    for ordered in (list(CHECKS.values()), reversed(list(CHECKS.values()))):
        findings = original
        for _, apply in ordered:
            findings, _ = apply(text, findings, normalize)
        ordered_predictions.append(findings)
    states = defaultdict(set)
    for name, (evidence, _, _) in checks.items():
        if evidence:
            states[CHECKS[name][0]].add(evidence.state)
    return {
        **row, "v4": sorted(original), "combined": sorted(combined),
        "order_conflict": any(prediction != combined for prediction in ordered_predictions),
        "opposite_evidence_states": sorted(code for code, values in states.items()
                                           if {"supported", "compliant"} <= values),
        "checks": {name: {"evidence": asdict(evidence) if evidence else None,
                          "added": added, "removed": removed}
                   for name, (evidence, added, removed) in checks.items()},
    }


def archived_cohort(name):
    references, _, _, codes, _, _, identity = sources(name)
    path = BASELINE / f"{name}.json"
    archive = load(path)
    if archive["source_artifacts_sha256"] != identity:
        raise ValueError(f"Original v4 inputs changed: {name}")
    for file, expected in archive["scoring_identity"].items():
        if digest(ROOT / file) != expected:
            raise ValueError(f"Original v4 scoring file changed: {file}")
    rows = []
    for ref, old in zip(references, archive["decisions"], strict=True):
        for key in ("scenario_id", "expected_decision", "expected_codes"):
            if ref[key] != old[key]:
                raise ValueError(f"Original v4 replay row mismatch: {name}")
        row = {key: ref[key] for key in ("description", "expected_decision", "expected_codes")}
        row["record"] = f'{ref["scenario_id"]}:{ref["language"]}'
        rows.append(compare(row, old["predicted_codes"]))
    return rows, codes, {**identity, path.relative_to(WORKSPACE).as_posix(): digest(path)}


def verified_addons(cutoff):
    accepted, fixtures = {}, {}
    for name in CHECKS:
        directory = ROOT / "evaluation" / name
        path = directory / "replay.json"
        report = load(path)
        if not all(report["gates"].values()) or report["verifier_cutoff"] != cutoff:
            raise ValueError(f"Standalone gates or v4 cutoff changed: {name}")
        for file, expected in report["addon_sha256"].items():
            if digest(ROOT / file) != expected:
                raise ValueError(f"Standalone source changed: {file}")
        accepted[name] = {"category": CHECKS[name][0], "replay_sha256": digest(path),
                          "gates": report["gates"], "source_sha256": report["addon_sha256"]}
        fixtures[name] = report["fresh_decisions"]
    return accepted, fixtures


def fresh_cohort(pilot, fixtures):
    rows = []
    for name, cases in fixtures.items():
        predictions = pilot.predict([case["description"] for case in cases])
        for case, codes in zip(cases, predictions, strict=True):
            if sorted(codes) != case["v4"]:
                raise ValueError(f"Original v4 fresh prediction changed: {name}:{case['record']}")
            row = {field: case[field] for field in ("description", "expected_decision", "expected_codes", "language")}
            row["record"] = f"{name}:{case['record']}"
            rows.append(compare(row, codes))
    return rows


def measure(rows, key):
    result = metrics([{**row, "predicted_codes": row[key]} for row in rows])
    tp, fp, fn = (result[field] for field in ("true_positives", "false_positives", "false_negatives"))
    result["f1"] = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    return result


def category_results(rows, codes):
    result = {}
    for code in codes:
        expected = {index for index, row in enumerate(rows) if code in (row["expected_codes"] or ())}
        counts = {}
        for key in ("v4", "combined"):
            found = {index for index, row in enumerate(rows) if code in row[key]}
            correct = len(found & expected)
            counts[key] = {"correct": correct, "false_positives": len(found - expected),
                           "precision": correct / len(found) if found else None,
                           "recall": correct / len(expected) if expected else None}
        result[code] = {"expected": len(expected), **counts}
    return result


def summarize(rows):
    new_errors, removed_correct, recovered, cleared, lost_complete = [], [], [], [], []
    by_check = {name: Counter() for name in CHECKS}
    duplicate_additions = []
    for row in rows:
        expected = set(row["expected_codes"] or ())
        before, after = set(row["v4"]), set(row["combined"])
        added, removed = after - before, before - after
        for target, codes in ((new_errors, added - expected), (removed_correct, removed & expected),
                              (recovered, added & expected), (cleared, removed - expected)):
            if codes:
                target.append({"record": row["record"], "codes": sorted(codes)})
        if len(expected) > 1 and before == expected and after != expected:
            lost_complete.append(row["record"])
        add_counts = Counter()
        for name, detail in row["checks"].items():
            own_added, own_removed = set(detail["added"]), set(detail["removed"])
            add_counts.update(own_added)
            by_check[name].update({"correct_added": len(own_added & expected),
                                   "incorrect_added": len(own_added - expected),
                                   "correct_removed": len(own_removed & expected),
                                   "incorrect_removed": len(own_removed - expected)})
        duplicate_additions.extend({"record": row["record"], "code": code, "checks": count}
                                   for code, count in add_counts.items() if count > 1)
    return {
        "descriptions": len(rows),
        "v4": measure(rows, "v4"), "combined": measure(rows, "combined"),
        "recovered_misses": recovered, "new_false_positives": new_errors,
        "removed_correct_findings": removed_correct, "cleared_baseline_false_positives": cleared,
        "lost_fully_correct_multi_violation_notes": lost_complete,
        "order_conflicts": [row["record"] for row in rows if row["order_conflict"]],
        "opposite_evidence_states": [{"record": row["record"], "codes": row["opposite_evidence_states"]}
                                     for row in rows if row["opposite_evidence_states"]],
        "deduplicated_additions": duplicate_additions,
        "add_on_effects": {name: {key: counts[key] for key in (
            "correct_added", "incorrect_added", "correct_removed", "incorrect_removed",
        )} for name, counts in by_check.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    cohorts, provenance = {}, {}
    for name in COHORTS:
        cohorts[name], codes, provenance[name] = archived_cohort(name)
    historical = cohorts[HISTORICAL]
    baseline = measure(historical, "v4")
    baseline_fields = ("true_positives", "false_positives", "false_negatives", "multi_exact", "multi_rows")
    if (len(historical), *(baseline[field] for field in baseline_fields)) != BASELINE_COUNTS:
        raise ValueError("Historical baseline differs from the requested frozen 804-description v4 replay")
    pilot = PilotReplay()
    cutoff = pilot.verifier.cutoff
    accepted, fixtures = verified_addons(cutoff)
    baseline_hash = digest(BASELINE / f"{HISTORICAL}.json")
    verifier_hash = digest(ARTIFACT / "metadata.json")
    archive_checks = pilot.verify_replay()
    cohorts["fresh_matched"] = fresh_cohort(pilot, fixtures)
    summaries = {name: summarize(rows) for name, rows in cohorts.items()}
    gates = {
        "original_historical_and_verifier_archives_preserved":
            baseline_hash == digest(BASELINE / f"{HISTORICAL}.json")
            and verifier_hash == digest(ARTIFACT / "metadata.json"),
        "no_new_false_positives": all(not s["new_false_positives"] for s in summaries.values()),
        "no_lost_correct_findings": all(not s["removed_correct_findings"] for s in summaries.values()),
        "no_lost_fully_correct_multi_violation_notes":
            all(not s["lost_fully_correct_multi_violation_notes"] for s in summaries.values()),
        "no_order_conflicts": all(not s["order_conflicts"] for s in summaries.values()),
    }
    report = {
        "purpose": "Combined offline development replay of the six individually verified add-ons.",
        "verifier_cutoff": cutoff, "verifier_metadata_sha256": verifier_hash,
        "original_v4_reproduced_rows": archive_checks,
        "sources": provenance, "accepted_add_ons": accepted,
        "combined_code_sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in (
            Path(__file__).resolve(), ROOT / "src/targeted_v4.py",
        )},
        "gates": gates, "metrics": summaries, "historical_per_category": category_results(historical, codes),
        "changed_decisions": {name: [row for row in rows if row["v4"] != row["combined"]]
                              for name, rows in cohorts.items()},
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"gates": gates, "historical": summaries[HISTORICAL]}, indent=2))
    if not all(gates.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
