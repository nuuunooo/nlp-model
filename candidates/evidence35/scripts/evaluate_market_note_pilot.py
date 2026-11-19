"""Run the market-note add-on over revised v4 and replay its development regressions."""

import argparse
import json
from pathlib import Path
import sys

from evaluate_liquor_regression import EVALUATION, PilotReplay, broad_regressions, changes, compare, measure
from recover_corroborated_recall import ROOT, digest, incident_spans, load, normalize
from src.inspection_evidence import assess_market_note
from src.liquor_consumption import load_consumption_policy
from src.liquor_evidence import sale_limits


def inspection_result(row, policy):
    findings, reviews, compliant = assess_market_note(
        row["description"], normalize, policy, market_inspection=True,
    )
    previous = set(row["revised_v4"])
    predictions = sorted(previous | findings.keys())
    reviews = {code: reason for code, reason in reviews.items() if code not in predictions}
    return {
        **row, "with_market_checks": predictions,
        "added_evidence": {code: reason for code, reason in findings.items() if code not in previous},
        "review_only": reviews, "observed_compliance": [code for code in compliant if code not in predictions],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    descriptions = json.load(sys.stdin)
    pilot = PilotReplay()
    verified = pilot.verify_replay()
    base = pilot.predict(descriptions)
    policy = load_consumption_policy()
    records = []
    for i, (text, codes) in enumerate(zip(descriptions, base, strict=True), 1):
        checks = [item for unit in incident_spans(text, normalize) for item in sale_limits(unit)]
        result = compare(text, codes, policy, checks)
        records.append(inspection_result({"record": i, "description": text, **result}, policy))

    broad, provenance = broad_regressions(policy)
    all_rows = [inspection_result(row, policy) for group in broad.values() for row in group]
    locked = load(EVALUATION / "liquor-safeguards-regression.json")["locked_consumption_records"]
    locked_rows = [inspection_result(row, policy) for row in locked]
    delta = changes(all_rows, "with_market_checks", "revised_v4")
    locked_delta = changes(locked_rows, "with_market_checks", "revised_v4")
    safe = all(item["counts"]["incorrect_added"] == item["counts"]["correct_removed"] == 0
               for item in (delta, locked_delta))
    report = {
        "purpose": "Market-note development fixes. The submitted descriptions informed this change.",
        "scope": "Offline market inspection notes. Market context identifies a note's otherwise unnamed entrance.",
        "v4_archive_checks": verified,
        "source_sha256": {file.name: digest(file) for file in (
            Path(__file__), ROOT / "src/inspection_evidence.py", ROOT / "src/liquor_consumption.py",
            EVALUATION / "liquor-safeguards-regression.json",
        )},
        "records": records,
        "development_regression": {
            "sources": provenance, "rows": len(all_rows), "changes": delta, "locked_consumption_changes": locked_delta,
            "no_new_errors_or_misses": safe, "before": measure(all_rows, "revised_v4"),
            "after": measure(all_rows, "with_market_checks"),
        },
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    for record in records:
        print(record["record"], record["with_market_checks"], record["review_only"], record["observed_compliance"])
    print("Broad changes:", delta["counts"], "Locked consumption changes:", locked_delta["counts"])


if __name__ == "__main__":
    main()
