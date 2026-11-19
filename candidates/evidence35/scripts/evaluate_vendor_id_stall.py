"""Run the stall ID check over original v4 and its synthetic regressions."""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from evaluate_pilot_consumption import PilotReplay
from recover_corroborated_recall import COHORTS, ROOT, WORKSPACE, digest, load, metrics, normalize, sources
from src.vendor_id_stall import CATEGORY, with_vendor_id_stall


EVALUATION = ROOT / "evaluation/vendor-id-stall"
BASELINE = ROOT / "evaluation/operational-evidence-recall-v4"


def compare(row, codes):
    findings, check = with_vendor_id_stall(row["description"], codes, normalize)
    return {**row, "v4": sorted(codes), "with_stall_id_check": sorted(findings),
            "stall_id_evidence": asdict(check) if check else None}


def archived_cohort(name):
    references, _, _, _, _, _, identity = sources(name)
    path = BASELINE / f"{name}.json"
    archive = load(path)
    if identity != archive["source_artifacts_sha256"]:
        raise ValueError(f"Original v4 inputs changed: {name}")
    for file, expected in archive["scoring_identity"].items():
        if digest(ROOT / file) != expected:
            raise ValueError(f"Original v4 scoring file changed: {file}")
    rows = []
    for ref, baseline in zip(references, archive["decisions"], strict=True):
        for key in ("scenario_id", "expected_decision", "expected_codes"):
            if ref[key] != baseline[key]:
                raise ValueError(f"Original v4 replay row mismatch: {name}")
        row = {key: ref[key] for key in ("description", "expected_decision", "expected_codes")}
        row["record"] = f'{ref["scenario_id"]}:{ref["language"]}'
        rows.append(compare(row, baseline["predicted_codes"]))
    return rows, {**identity, path.relative_to(WORKSPACE).as_posix(): digest(path)}


def fresh_cohort(pilot):
    cases = load(EVALUATION / "fresh-cases.json")
    baseline = pilot.predict([case["description"] for case in cases])
    result = []
    for case, codes in zip(cases, baseline, strict=True):
        state = case["state"]
        row = {**case, "record": f'{case["group"]}:{state}',
               "expected_codes": [CATEGORY] if state == "supported" else [],
               "expected_decision": {"supported": "accept", "compliant": "clear", "insufficient": "abstain"}[state]}
        result.append(compare(row, codes))
    return result


def summarize(rows):
    expected = {i for i, row in enumerate(rows) if CATEGORY in (row["expected_codes"] or ())}
    before = {i for i, row in enumerate(rows) if CATEGORY in row["v4"]}
    after = {i for i, row in enumerate(rows) if CATEGORY in row["with_stall_id_check"]}
    summaries = {}
    for key, found in (("v4", before), ("with_stall_id_check", after)):
        tp, fp, fn = len(found & expected), len(found - expected), len(expected - found)
        summaries[key] = {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
                          "precision": tp / len(found) if found else None,
                          "recall": tp / len(expected) if expected else None}
    return {
        "vendor_identification": summaries,
        "all_categories": {key: metrics([{**row, "predicted_codes": row[key]} for row in rows])
                           for key in ("v4", "with_stall_id_check")},
        "recovered_misses": [rows[i]["record"] for i in sorted((after - before) & expected)],
        "new_false_positives": [rows[i]["record"] for i in sorted(after - before - expected)],
        "removed_findings": [row["record"] for row in rows if set(row["v4"]) - set(row["with_stall_id_check"])],
        "other_category_changes": [
            row["record"] for row in rows
            if set(row["v4"]) - {CATEGORY} != set(row["with_stall_id_check"]) - {CATEGORY}
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
    cohorts["fresh_matched"] = fresh_cohort(pilot)
    summaries = {name: summarize(rows) for name, rows in cohorts.items()}
    states = Counter((row["language"], row["state"]) for row in cohorts["fresh_matched"]
                     if row["stall_id_evidence"] and row["stall_id_evidence"]["state"] == row["state"])
    gates = {
        "no_new_false_positives": all(not s["new_false_positives"] for s in summaries.values()),
        "all_original_v4_findings_preserved": all(not s["removed_findings"] for s in summaries.values()),
        "other_categories_unchanged": all(not s["other_category_changes"] for s in summaries.values()),
        "all_fresh_evidence_states_correct": sum(states.values()) == len(cohorts["fresh_matched"]),
    }
    report = {
        "purpose": "Offline replay of original v4 and synthetic development examples.",
        "verifier_cutoff": pilot.verifier.cutoff,
        "original_v4_reproduced_rows": archive_checks,
        "sources": provenance,
        "addon_sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in (
            Path(__file__).resolve(), ROOT / "src/vendor_id_stall.py", EVALUATION / "fresh-cases.json",
        )},
        "gates": gates, "metrics": summaries,
        "fresh_state_counts": {f"{language}:{state}": count for (language, state), count in sorted(states.items())},
        "fresh_decisions": cohorts["fresh_matched"],
        "archived_decision_changes": {name: [row for row in cohorts[name] if row["v4"] != row["with_stall_id_check"]]
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
