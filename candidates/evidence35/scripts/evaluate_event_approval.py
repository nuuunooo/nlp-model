"""Replay original v4 with the isolated Entertainment Activities add-on."""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from evaluate_pilot_consumption import PilotReplay
from recover_corroborated_recall import ROOT, WORKSPACE, digest, load, metrics, normalize, sources
from src.event_approval import CATEGORY, with_event_approval


EVALUATION = ROOT / "evaluation/event-approval"
BASELINE = ROOT / "evaluation/operational-evidence-recall-v4"
COHORTS = ("validation_verified", "test_regression_verified", "challenge_verified")


def compare(row, baseline):
    before = set(baseline)
    after, evidence = with_event_approval(row["description"], before, normalize)
    return {**row, "v4": sorted(before), "with_event_approval": sorted(after),
            "approval_evidence": asdict(evidence) if evidence else None}


def category_metrics(rows, key):
    expected = [CATEGORY in (row["expected_codes"] or ()) for row in rows]
    predicted = [CATEGORY in row[key] for row in rows]
    tp = sum(a and b for a, b in zip(expected, predicted, strict=True))
    fp = sum(b and not a for a, b in zip(expected, predicted, strict=True))
    fn = sum(a and not b for a, b in zip(expected, predicted, strict=True))
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}


def summarize(rows):
    added = [row for row in rows if CATEGORY in row["with_event_approval"] and CATEGORY not in row["v4"]]
    removed = [row for row in rows if CATEGORY in row["v4"] and CATEGORY not in row["with_event_approval"]]
    return {
        "all_categories": {key: metrics([{**row, "predicted_codes": row[key]} for row in rows])
                           for key in ("v4", "with_event_approval")},
        "entertainment_activities": {key: category_metrics(rows, key) for key in ("v4", "with_event_approval")},
        "recovered_misses": [row["record"] for row in added if CATEGORY in (row["expected_codes"] or ())],
        "new_false_positives": [row["record"] for row in added if CATEGORY not in (row["expected_codes"] or ())],
        "removed_correct_findings": [row["record"] for row in removed if CATEGORY in (row["expected_codes"] or ())],
        "cleared_baseline_false_positives": [row["record"] for row in removed if CATEGORY not in (row["expected_codes"] or ())],
        "other_category_changes": [row["record"] for row in rows if
                                   set(row["v4"]) - {CATEGORY} != set(row["with_event_approval"]) - {CATEGORY}],
    }


def archived_cohorts():
    results, provenance = {}, {}
    for name in COHORTS:
        references, _, _, _, _, _, identity = sources(name)
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
        results[name] = rows
        provenance[name] = {**identity, path.relative_to(WORKSPACE).as_posix(): digest(path)}
    return results, provenance


def fresh_cohort(pilot):
    path = EVALUATION / "fresh-cases.json"
    cases = load(path)
    baseline = pilot.predict([row["description"] for row in cases])
    results = []
    for case, codes in zip(cases, baseline, strict=True):
        state = case["state"]
        row = {**case, "record": f'{case["group"]}:{state}',
               "expected_decision": {"supported": "accept", "compliant": "clear", "insufficient": "abstain"}[state],
               "expected_codes": [CATEGORY] if state == "supported" else []}
        results.append(compare(row, codes))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    cohorts, provenance = archived_cohorts()
    pilot = PilotReplay()
    archive_checks = pilot.verify_replay()
    cohorts["fresh_matched"] = fresh_cohort(pilot)
    summaries = {name: summarize(rows) for name, rows in cohorts.items()}
    historical = summaries["test_regression_verified"]["entertainment_activities"]["with_event_approval"]
    states = Counter((row["language"], row["state"]) for row in cohorts["fresh_matched"]
                     if row["approval_evidence"] and row["approval_evidence"]["state"] == row["state"])
    gates = {
        "historical_at_least_26_correct_zero_incorrect":
            historical["true_positives"] >= 26 and historical["false_positives"] == 0,
        "no_added_false_positives": all(not summary["new_false_positives"] for summary in summaries.values()),
        "all_correct_baseline_findings_preserved":
            all(not summary["removed_correct_findings"] for summary in summaries.values()),
        "other_categories_unchanged": all(not summary["other_category_changes"] for summary in summaries.values()),
        "all_fresh_evidence_states_correct": sum(states.values()) == len(cohorts["fresh_matched"]),
        "zero_fresh_incorrect_event_findings":
            summaries["fresh_matched"]["entertainment_activities"]["with_event_approval"]["false_positives"] == 0,
    }
    report = {
        "purpose": "Offline development replay with synthetic examples and previously inspected cohorts.",
        "comparison": "Add a documented approval breach and withhold approval-only findings on a verified pass "
                      "or explicitly unverifiable approval. Preserve independent event findings.",
        "verifier_cutoff": pilot.verifier.cutoff,
        "original_v4_reproduced_rows": archive_checks,
        "sources": provenance,
        "addon_sha256": {path.relative_to(ROOT).as_posix(): digest(path) for path in
                         (Path(__file__).resolve(), ROOT / "src/event_approval.py", EVALUATION / "fresh-cases.json")},
        "gates": gates, "metrics": summaries,
        "fresh_state_counts": {f"{lang}:{state}": count for (lang, state), count in sorted(states.items())},
        "fresh_decisions": cohorts["fresh_matched"],
        "archived_decision_changes": {name: [row for row in rows if row["v4"] != row["with_event_approval"]]
                                      for name, rows in cohorts.items() if name in COHORTS},
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"gates": gates, "metrics": summaries}, indent=2))
    if not all(gates.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
