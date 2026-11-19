"""Replay the isolated repair-closure check against original v4."""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from evaluate_pilot_consumption import PilotReplay
from evaluate_stall_operating_days import BASELINE, summarize as occupancy_summary
from recover_corroborated_recall import COHORTS, ROOT, WORKSPACE, digest, load, normalize, sources
from src.stall_repair_closure import CATEGORY, with_repair_closure


EVALUATION = ROOT / "evaluation/stall-repair-closure"


def compare(row, baseline):
    findings, evidence = with_repair_closure(row["description"], baseline, normalize)
    return {**row, "v4": sorted(baseline), "with_repair_closure": sorted(findings),
            "repair_closure_evidence": asdict(evidence) if evidence else None}


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
        for field in ("scenario_id", "expected_decision", "expected_codes"):
            if ref[field] != old[field]:
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
    # Use the same per-category and whole-pipeline metrics as the operating-days replay.
    result = occupancy_summary([{**row, "with_operating_days": row["with_repair_closure"],
                                 "operating_days_evidence": row["repair_closure_evidence"]} for row in rows])
    for name in ("stall_occupancy", "all_categories"):
        result[name]["with_repair_closure"] = result[name].pop("with_operating_days")
    return result


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
                     if row["repair_closure_evidence"] and row["repair_closure_evidence"]["state"] == row["state"])
    gates = {
        "no_new_false_positives": all(not s["new_false_positives"] for s in summaries.values()),
        "all_original_v4_findings_preserved": all(not s["removed_findings"] for s in summaries.values()),
        "other_categories_unchanged": all(not s["other_category_changes"] for s in summaries.values()),
        "all_fresh_evidence_states_correct": sum(states.values()) == len(fresh),
    }
    report = {
        "purpose": "Offline synthetic development replay of the Stall Occupancy repair-closure check.",
        "verifier_cutoff": pilot.verifier.cutoff,
        "original_v4_reproduced_rows": archive_checks,
        "sources": provenance,
        "addon_sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in (
            Path(__file__).resolve(), ROOT / "src/stall_repair_closure.py", ROOT / "src/event_approval.py",
            ROOT / "src/stall_operating_days.py", ROOT / "src/vendor_id_stall.py",
            ROOT / "scripts/evaluate_stall_operating_days.py", fresh_path,
        )},
        "gates": gates, "metrics": summaries,
        "fresh_state_counts": {f"{lang}:{state}": count for (lang, state), count in sorted(states.items())},
        "fresh_decisions": fresh,
        "archived_decision_changes": {name: [row for row in cohorts[name] if row["v4"] != row["with_repair_closure"]]
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
