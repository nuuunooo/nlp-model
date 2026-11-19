"""Run the shared incident candidate on descriptions or development regressions."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import sys

CANDIDATE = Path(__file__).resolve().parents[1]
WORKSPACE = CANDIDATE.parents[1]
sys.path.insert(0, str(CANDIDATE))
sys.path.append(str(WORKSPACE))

from src.shared_incidents import PIPELINE_VERSION, SharedIncidentPipeline
from evaluate_pipeline_verifier import metrics


def digest(path):
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=WORKSPACE / "models/setfit-e5-synthetic-v2")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--regressions", type=Path, help="Write a new offline regression report here. Otherwise read one description per stdin line.")
    args = parser.parse_args()
    pipeline = SharedIncidentPipeline(args.model, args.artifact)
    if args.regressions is None:
        descriptions = [line.rstrip("\r\n") for line in sys.stdin]
        for number, result in enumerate(pipeline.analyze_many(descriptions), 1):
            print(json.dumps({"record": number, **result}, ensure_ascii=False))
        return

    if args.regressions.exists():
        parser.error("Use a new regression report path")
    regression = WORKSPACE / "evaluation/candidate34"
    cohorts = {
        "synthetic_validation": "validation_verified.json",
        "historical_synthetic": "test_regression_verified.json",
        "synthetic_challenge": "challenge_verified.json",
    }
    report = {
        "version": PIPELINE_VERSION, "artifact": str(args.artifact),
        "support_cutoff": pipeline.verifier.cutoff,
        "artifact_metadata_sha256": digest(args.artifact / "metadata.json"),
        "runtime_sha256": {name: digest(CANDIDATE / "src" / name) for name in (
            "shared_incidents.py", "structured_evidence.py", "engine.py", "incidents.py",
            "description_evidence.py", "reweigh.py", "evidence_verifier.py", "setfit_classifier.py",
        )},
        "purpose": "Previously inspected development regressions. Market descriptions used in fitting are excluded.",
        "cohorts": {},
    }
    for name, file in cohorts.items():
        rows = json.loads((regression / file).read_text(encoding="utf-8"))["decisions"]
        results = pipeline.analyze_many([row["description"] for row in rows])
        decisions = [{
            "scenario_id": row["scenario_id"], "language": row["language"],
            "expected_codes": row["expected_codes"], "expected_decision": row["expected_decision"],
            "predicted_codes": sorted(finding["code"] for finding in result["findings"]),
            "support_sources": {finding["code"]: finding["reason"] for finding in result["findings"]},
        } for row, result in zip(rows, results, strict=True)]
        report["cohorts"][name] = {
            "records": len(decisions), "dataset_sha256": digest(regression / file),
            "metrics": metrics(decisions), "decisions": decisions,
        }
        print(name, json.dumps(report["cohorts"][name]["metrics"]), flush=True)
    with args.regressions.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
