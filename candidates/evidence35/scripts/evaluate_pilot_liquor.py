"""Measure the liquor comparison against previously inspected development rows."""

import argparse
import json
from pathlib import Path
import sys

from evaluate_pilot_evidence import (
    Addition, PRIOR, REGRESSIONS, ROOT, VALIDATION, digest, incident_spans, load, metrics, normalize, sources, summarize,
)
from src.liquor_evidence import (
    MARKET_DRINKING_POLICY_ID, POLICY_FILE, load_pilot_policy, market_drinking_comparisons,
    policy_comparisons, sale_limits,
)


ROUTES = (("Liquor", "verified_buyer_age"), ("Liquor", "documented_liquor_sale_window"))


def evaluate_synthetic(batch, *, market_drinking=False):
    records = batch["records"]
    if market_drinking:
        policy_id = MARKET_DRINKING_POLICY_ID
        comparisons = [list(market_drinking_comparisons(row["description"], normalize)) for row in records]
    else:
        policy = load_pilot_policy()
        policy_id = policy.policy_id
        comparisons = [list(policy_comparisons(row["description"], normalize, policy)) for row in records]
    baseline, updated, results = [], [], []
    for row, checks in zip(records, comparisons, strict=True):
        original_codes = row["v4_codes"]
        added = ["Liquor"] if any(state == "supported" for state, _ in checks) else []
        retained = set(original_codes)
        if market_drinking:
            # The submitted batch covers consumption only, so score Liquor under its location rule.
            retained.discard("Liquor")
        predictions = sorted(retained | set(added))
        expected = {"expected_codes": row["expected_codes"], "expected_decision": row["expected_decision"]}
        baseline.append({**expected, "predicted_codes": original_codes})
        updated.append({**expected, "predicted_codes": predictions})
        results.append({
            **row, "with_policy_codes": predictions,
            "comparisons": [{"state": state, "fact": reason} for state, reason in checks],
        })
    before, after = metrics(baseline), metrics(updated)
    for result in (before, after):
        if not result["true_positives"] + result["false_positives"]:
            result["precision"] = None
    return {
        "purpose": "Synthetic development retest. These descriptions informed the parser change.",
        "policy_id": policy_id, "policy_sha256": None if market_drinking else digest(POLICY_FILE),
        "baseline_source": "Recorded v4 decisions from the exact submitted descriptions before the policy change.",
        "scorer_sha256": {file.name: digest(file) for file in (
            Path(__file__), ROOT / "src/liquor_evidence.py", ROOT / "src/pilot_evidence.py",
        )},
        "v4_metrics": before, "with_policy_metrics": after, "records": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    batch = parser.add_mutually_exclusive_group()
    batch.add_argument("--synthetic-batch", help="Replay a synthetic sales batch JSON file. Use '-' for stdin.")
    batch.add_argument("--market-drinking-batch", help="Replay a consumption-only batch JSON file. Use '-' for stdin.")
    args = parser.parse_args()
    path = args.market_drinking_batch or args.synthetic_batch
    report = (evaluate_synthetic(json.load(sys.stdin) if path == "-" else load(Path(path)),
                                 market_drinking=bool(args.market_drinking_batch))
              if path else evaluate_historical())
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def evaluate_historical():
    report = {
        "purpose": "Historical misses informed development. This is an in-sample diagnostic, not release evidence.",
        "scorer_sha256": {file.name: digest(file) for file in (
            Path(__file__), ROOT / "src/liquor_evidence.py", ROOT / "src/pilot_evidence.py",
        )},
        "cohorts": {},
    }
    for cohort in (VALIDATION, *REGRESSIONS):
        references, _, _, _, _, _, identity = sources(cohort)
        prior = PRIOR / f"{cohort}.json"
        decisions = load(prior)["decisions"]
        additions = {
            Addition(index, "Liquor", route, unit.context)
            for index, (reference, before) in enumerate(zip(references, decisions, strict=True))
            if "Liquor" not in before["predicted_codes"]
            for unit in incident_spans(reference["description"], normalize)
            for state, route in sale_limits(unit) if state == "supported"
        }
        replay = summarize(decisions, references, sorted(additions, key=lambda a: (a.index, a.route, a.evidence)), ROUTES)
        report["cohorts"][cohort] = {"source_artifacts_sha256": identity, "v4_sha256": digest(prior), **replay}
        print(cohort, replay["metrics"], flush=True)
    return report


if __name__ == "__main__":
    main()
