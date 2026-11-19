"""Replay the Liquor safeguards on the locked batches and development regressions."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from evaluate_pilot_consumption import PilotReplay
from recover_corroborated_recall import BASELINES, ROOT, WORKSPACE, digest, incident_spans, load, metrics, normalize, sources, verify_breach
from src.liquor_consumption import ALCOHOL, CONSUMPTION, POLICY_FILE, consumption_evidence, consumption_safeguard, load_consumption_policy
from src.liquor_evidence import COMPLETED_SALE, POLICY_FILE as SALE_POLICY_FILE, load_pilot_policy, policy_comparisons, sale_limits
from src.pilot_evidence import eligible_incident


EVALUATION = ROOT / "evaluation/pilot-targeted-evidence"
PRIOR = ROOT / "evaluation/operational-evidence-recall-v4"
FROZEN = WORKSPACE / "evaluation/multi-incident-33"
LOCKED_CONSUMPTION = "968ced47c0553a904de590f2a90a7aa1c55b721baf85d879c6bface402314b65"
SERVICE = re.compile(r"\b(?:served|dispensed|poured|nagsalin|nagbuhos|inihain)\b")
VARIANTS = ("frozen_33", "v4", "v4_age_time", "v4_consumption", "revised_v4")


def independent_liquor_evidence(description):
    """Preserve a separate supported liquor sale or service in a mixed note."""
    for unit in incident_spans(description, normalize):
        observed = unit.text
        if (eligible_incident(unit) and not CONSUMPTION.search(observed) and re.search(ALCOHOL, observed)
                and (COMPLETED_SALE.search(observed) or SERVICE.search(observed))
                and verify_breach("Liquor", unit)):
            return True
    return False


def compare(description, prior, consumption_policy, sale_checks):
    sale_findings = sorted({route for state, route in sale_checks if state == "supported"})
    drinking = sorted({route for route, _ in consumption_evidence(description, normalize, consumption_policy)})
    prior = set(prior)
    with_sale = prior | ({"Liquor"} if sale_findings else set())
    with_drinking = prior | ({"Liquor"} if drinking else set())
    revised = with_sale | with_drinking
    veto = None
    if "Liquor" in revised:
        veto = consumption_safeguard(
            description, normalize, drinking,
            independent_liquor_evidence=bool(sale_findings) or independent_liquor_evidence(description),
        )
        if veto:
            revised.remove("Liquor")
    return {
        "v4": sorted(prior), "v4_age_time": sorted(with_sale), "v4_consumption": sorted(with_drinking),
        "revised_v4": sorted(revised), "age_time_evidence": sale_findings,
        "consumption_evidence": drinking, "consumption_veto": veto,
    }


def measure(rows, key):
    result = metrics([{**row, "predicted_codes": row[key]} for row in rows])
    tp, fp, fn = (result[name] for name in ("true_positives", "false_positives", "false_negatives"))
    result["precision"] = tp / (tp + fp) if tp + fp else None
    result["f1"] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    result["compliant_records"] = sum(row["expected_decision"] == "clear" for row in rows)
    result["abstention_records"] = sum(row["expected_decision"] == "abstain" for row in rows)
    return result


def changes(rows, candidate, baseline="v4"):
    counts = Counter()
    details = []
    for row in rows:
        expected = set(row["expected_codes"] or ())
        before, after = set(row[baseline]), set(row[candidate])
        added, removed = after - before, before - after
        if added or removed:
            counts.update({
                "correct_added": len(added & expected), "incorrect_added": len(added - expected),
                "correct_removed": len(removed & expected), "incorrect_removed": len(removed - expected),
            })
            details.append({key: row[key] for key in (
                "record", "description", "expected_decision", "expected_codes", "age_time_evidence",
                "consumption_evidence", "consumption_veto",
            )} | {"added": sorted(added), "removed": sorted(removed)})
    return {"counts": {key: counts[key] for key in (
        "correct_added", "incorrect_added", "correct_removed", "incorrect_removed",
    )}, "records": details}


def broad_regressions(consumption_policy):
    cohorts = {}
    provenance = {}
    for name, baseline_name in BASELINES.items():
        references, _, frozen, _, _, _, identity = sources(name)
        prior_path = PRIOR / f"{name}.json"
        prior = load(prior_path)
        for path, expected in prior["source_artifacts_sha256"].items():
            if digest(WORKSPACE / path) != expected:
                raise ValueError(f"Archived v4 input changed: {path}")
        for path, expected in prior["scoring_identity"].items():
            if digest(ROOT / path) != expected:
                raise ValueError(f"Archived v4 scorer changed: {path}")
        rows = []
        for original, base, old in zip(references, prior["decisions"], frozen, strict=True):
            if (original["scenario_id"], original["expected_decision"], original["expected_codes"]) != (
                base["scenario_id"], base["expected_decision"], base["expected_codes"]
            ):
                raise ValueError("v4 labels or row order changed")
            text = original["description"]
            # Broad cohorts carry their own rules. The ten-note synthetic cutoff is scoped to that batch.
            sale_checks = [item for unit in incident_spans(text, normalize) for item in sale_limits(unit)]
            rows.append({
                "record": f'{original["scenario_id"]}:{original["language"]}', "description": text,
                "expected_decision": base["expected_decision"], "expected_codes": base["expected_codes"],
                "frozen_33": old["predicted_codes"],
                **compare(text, base["predicted_codes"], consumption_policy, sale_checks),
            })
        cohorts[name] = rows
        identity[prior_path.relative_to(WORKSPACE).as_posix()] = digest(prior_path)
        identity[(FROZEN / f"{baseline_name}.json").relative_to(WORKSPACE).as_posix()] = digest(FROZEN / f"{baseline_name}.json")
        provenance[name] = identity
    return cohorts, provenance


def consumption_retest(consumption_policy):
    batch = EVALUATION / "liquor-consumption-batch.json"
    if digest(batch) != LOCKED_CONSUMPTION:
        raise ValueError("Consumption batch changed since the first run")
    rows = load(batch)["records"]
    pilot = PilotReplay()
    archive_checks = pilot.verify_replay()
    predictions = pilot.predict([row["description"] for row in rows])
    first_run = load(EVALUATION / "liquor-consumption-results.json")
    if first_run["batch_sha256"] != LOCKED_CONSUMPTION:
        raise ValueError("Prior consumption result belongs to a different batch")
    compared = []
    for row, before, old in zip(rows, predictions, first_run["records"], strict=True):
        if sorted(before) != old["v4_codes"] or row["description"] != old["description"]:
            raise ValueError(f'Could not reproduce v4 on record {row["record"]}')
        compared.append({
            **row, "expected_codes": ["Liquor"] if row["expected_decision"] == "accept"
            else [] if row["expected_decision"] == "clear" else None,
            **compare(row["description"], before, consumption_policy, ()),
        })
    return compared[:3], compared[3:], archive_checks


def age_time_retest(consumption_policy):
    source = EVALUATION / "liquor-policy-recheck.json"
    policy = load_pilot_policy()
    rows = []
    for row in load(source)["records"]:
        text = row["description"]
        rows.append({**row, **compare(text, row["v4_codes"], consumption_policy,
                                     policy_comparisons(text, normalize, policy))})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    policy = load_consumption_policy()
    known, consumption, archive_checks = consumption_retest(policy)
    age_time = age_time_retest(policy)
    broad, provenance = broad_regressions(policy)
    all_broad = [row for cohort in broad.values() for row in cohort]
    rows = {"known_consumption": known, "consumption_20": consumption, "age_time_10": age_time,
            **broad, "broader_total": all_broad}
    metrics_by_cohort = {name: {key: measure(group, key) for key in VARIANTS if key in group[0]}
                         for name, group in rows.items()}
    broader_changes = {key: changes(all_broad, key) for key in VARIANTS[2:]}
    result = {
        "purpose": "Previously inspected synthetic development regressions. Independent operational test data was excluded.",
        "comparison_scope": "Archived frozen 3.3 and v4 outputs for the broader cohorts. Recomputed v4 on the locked consumption batch.",
        "source_sha256": {file.name: digest(file) for file in (
            Path(__file__), ROOT / "src/liquor_consumption.py", ROOT / "src/liquor_evidence.py",
            ROOT / "scripts/evaluate_pilot_consumption.py", POLICY_FILE, SALE_POLICY_FILE,
            EVALUATION / "liquor-consumption-batch.json", EVALUATION / "liquor-policy-recheck.json",
        )},
        "v4_archive_checks": archive_checks,
        "broad_sources": provenance, "metrics": metrics_by_cohort,
        "broader_changes": broader_changes, "consumption_20_changes_vs_additive": changes(consumption, "revised_v4", "v4_consumption"),
        "locked_consumption_records": known + consumption, "age_time_records": age_time,
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"consumption_20": metrics_by_cohort["consumption_20"],
                      "broader_total": metrics_by_cohort["broader_total"],
                      "broad_deltas": {key: value["counts"] for key, value in broader_changes.items()}}, indent=2))


if __name__ == "__main__":
    main()
