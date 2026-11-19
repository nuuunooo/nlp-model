"""Replay the isolated loading and idling check against original v4."""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from evaluate_pilot_consumption import PilotReplay
from recover_corroborated_recall import COHORTS, ROOT, WORKSPACE, digest, load, metrics, normalize, sources
from src.traffic_loading import CATEGORY, with_traffic_loading


EVALUATION = ROOT / "evaluation/traffic-loading"
BASELINE = ROOT / "evaluation/operational-evidence-recall-v4"


def compare(row, baseline):
    findings, check = with_traffic_loading(row["description"], baseline, normalize)
    return {**row, "v4": sorted(baseline), "with_traffic_check": sorted(findings),
            "traffic_evidence": asdict(check) if check else None}


def archived_cohort(name):
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
    return rows, {**identity, path.relative_to(WORKSPACE).as_posix(): digest(path)}


def fresh_cohort(pilot, cases):
    baseline = pilot.predict([case["description"] for case in cases])
    rows = []
    for case, codes in zip(cases, baseline, strict=True):
        state = case["state"]
        row = {**case, "record": f'{case["group"]}:{state}',
               "expected_codes": [CATEGORY] if state == "supported" else [],
               "expected_decision": {"supported": "accept", "compliant": "clear", "insufficient": "abstain"}[state]}
        rows.append(compare(row, codes))
    return rows


def summarize(rows):
    expected = {i for i, row in enumerate(rows) if CATEGORY in (row["expected_codes"] or ())}
    before = {i for i, row in enumerate(rows) if CATEGORY in row["v4"]}
    after = {i for i, row in enumerate(rows) if CATEGORY in row["with_traffic_check"]}
    traffic = {}
    for key, findings in (("v4", before), ("with_traffic_check", after)):
        tp, fp, fn = len(findings & expected), len(findings - expected), len(expected - findings)
        traffic[key] = {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
                        "precision": tp / len(findings) if findings else None,
                        "recall": tp / len(expected) if expected else None}
    return {
        "traffic": traffic,
        "all_categories": {key: metrics([{**row, "predicted_codes": row[key]} for row in rows])
                           for key in ("v4", "with_traffic_check")},
        "recovered_misses": [rows[i]["record"] for i in sorted((after - before) & expected)],
        "new_false_positives": [rows[i]["record"] for i in sorted(after - before - expected)],
        "removed_findings": [row["record"] for row in rows if set(row["v4"]) - set(row["with_traffic_check"])],
        "other_category_changes": [
            row["record"] for row in rows
            if set(row["v4"]) - {CATEGORY} != set(row["with_traffic_check"]) - {CATEGORY}
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    cohorts, provenance = {}, {}
    for name in COHORTS:
        cohorts[name], provenance[name] = archived_cohort(name)
    pilot = PilotReplay()
    archive_checks = pilot.verify_replay()
    fresh_path = EVALUATION / "fresh-cases.json"
    fresh = fresh_cohort(pilot, load(fresh_path))
    cohorts["fresh_matched"] = fresh
    summaries = {name: summarize(rows) for name, rows in cohorts.items()}
    states = Counter((row["language"], row["state"]) for row in fresh
                     if row["traffic_evidence"] and row["traffic_evidence"]["state"] == row["state"])
    gates = {
        "no_new_false_positives": all(not s["new_false_positives"] for s in summaries.values()),
        "all_original_v4_findings_preserved": all(not s["removed_findings"] for s in summaries.values()),
        "other_categories_unchanged": all(not s["other_category_changes"] for s in summaries.values()),
        "all_fresh_evidence_states_correct": sum(states.values()) == len(fresh),
    }
    report = {
        "purpose": "Offline synthetic development replay for loading locations and engine-off rules.",
        "verifier_cutoff": pilot.verifier.cutoff,
        "original_v4_reproduced_rows": archive_checks,
        "sources": provenance,
        "addon_sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in (
            Path(__file__).resolve(), ROOT / "src/traffic_loading.py", fresh_path,
        )},
        "gates": gates, "metrics": summaries,
        "fresh_state_counts": {f"{lang}:{state}": count for (lang, state), count in sorted(states.items())},
        "fresh_decisions": fresh,
        "archived_decision_changes": {name: [row for row in cohorts[name] if row["v4"] != row["with_traffic_check"]]
                                      for name in COHORTS},
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"gates": gates, "metrics": summaries}, indent=2))
    if not all(gates.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
