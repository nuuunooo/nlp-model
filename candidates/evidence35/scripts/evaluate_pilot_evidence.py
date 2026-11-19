"""Select evidence additions on validation and replay them over the v4 pilot."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from recover_corroborated_recall import ROOT, WORKSPACE, digest, incident_spans, load, metrics, normalize, sources
from candidates.description34.src.breach_evidence import quantitative_proof
from scripts.observed_breach_recovery import grounded_codes
from src.pilot_evidence import eligible_incident, shared_evidence, targeted_evidence


PRIOR = ROOT / "evaluation/operational-evidence-recall-v4"
VALIDATION = "validation_verified"
REGRESSIONS = ("test_regression_verified", "challenge_verified")
QUANTITATIVE = {"Price Monitoring", "Market Fees & Surcharges"}


@dataclass(frozen=True)
class Addition:
    index: int
    code: str
    route: str
    evidence: str

    @property
    def key(self):
        return self.code, self.route


def collect(name):
    references, seed, _, codes, scores, _, identity = sources(name)
    path = PRIOR / f"{name}.json"
    prior = load(path)
    for filename, expected in prior["scoring_identity"].items():
        if digest(ROOT / filename) != expected:
            raise ValueError(f"Prior scoring code changed: {filename}")
    decisions = prior["decisions"]
    for original, current in zip(seed, decisions, strict=True):
        if (original["scenario_id"], original["expected_codes"], original["expected_decision"]) != (
            current["scenario_id"], current["expected_codes"], current["expected_decision"]
        ):
            raise ValueError(f"Prior cohort ordering or labels changed: {name}")
    identity[path.relative_to(WORKSPACE).as_posix()] = digest(path)

    additions = set()
    for index, (reference, prior_row) in enumerate(zip(references, decisions, strict=True)):
        existing = set(prior_row["predicted_codes"])
        for unit in incident_spans(reference["description"], normalize):
            if not eligible_incident(unit):
                continue
            ranked = np.argsort(-scores[unit.context], kind="stable")[:3]
            nominations = [codes[position] for position in ranked if codes[position] not in existing]
            proofs = list(shared_evidence(unit, nominations))
            proofs.extend(targeted_evidence(unit))
            proofs.extend((code, "grounded_observed_breach") for code in grounded_codes(unit))
            proofs.extend((code, "verified_quantitative_comparison") for code in nominations
                          if code in QUANTITATIVE and quantitative_proof(code, unit) is True)
            additions.update(Addition(index, code, route, unit.context)
                             for code, route in proofs if code not in existing)
    return decisions, references, sorted(additions, key=lambda a: (a.index, a.code, a.route, a.evidence)), identity


def supported(addition, decisions):
    row = decisions[addition.index]
    return row["expected_decision"] == "accept" and addition.code in (row["expected_codes"] or ())


def select(decisions, additions):
    by_route = defaultdict(list)
    for addition in additions:
        by_route[addition.key].append(addition)
    return sorted(key for key, matches in by_route.items()
                  if len({decisions[match.index]["scenario_id"] for match in matches}) >= 2
                  and all(supported(match, decisions) for match in matches))


def summarize(decisions, references, additions, routes):
    before = [set(row["predicted_codes"]) for row in decisions]
    after = [codes.copy() for codes in before]
    selected = set(map(tuple, routes))
    matched = []
    for addition in additions:
        if addition.key in selected:
            after[addition.index].add(addition.code)
            reference = references[addition.index]
            matched.append({
                "scenario_id": reference["scenario_id"], "language": reference["language"],
                "code": addition.code, "route": addition.route, "evidence": addition.evidence,
                "supported_by_label": supported(addition, decisions),
            })
    result = [dict(row, predicted_codes=sorted(codes)) for row, codes in zip(decisions, after, strict=True)]
    return {"prior_metrics": metrics(decisions), "metrics": metrics(result), "additions": matched}


def route_summary(decisions, additions):
    by_route = defaultdict(dict)
    for addition in additions:
        by_route[addition.key][addition.index] = supported(addition, decisions)
    return {
        " / ".join(key): {
            "correct": sum(matches.values()), "incorrect": len(matches) - sum(matches.values()),
            "distinct_correct_scenarios": len({decisions[index]["scenario_id"] for index, correct in matches.items()
                                               if correct}),
        }
        for key, matches in sorted(by_route.items())
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--regressions", action="store_true")
    args = parser.parse_args()
    identity = {
        path.relative_to(WORKSPACE).as_posix(): digest(path)
        for path in (Path(__file__), ROOT / "src/pilot_evidence.py", ROOT / "src/structured_evidence.py",
                     ROOT / "src/description_evidence.py", ROOT / "scripts/observed_breach_recovery.py")
    }
    if args.regressions:
        selection = load(args.output / f"{VALIDATION}.json")
        if selection["identity"] != identity:
            raise ValueError("The validation-selected evidence code changed")
        routes = selection["selected_routes"]
        cohorts = REGRESSIONS
    else:
        args.output.mkdir(exist_ok=False)
        cohorts = (VALIDATION,)
    for name in cohorts:
        decisions, references, additions, source_identity = collect(name)
        if not args.regressions:
            routes = select(decisions, additions)
        report = {
            "purpose": "Additive development regression over the unchanged v4 pilot.",
            "identity": identity, "source_artifacts_sha256": source_identity, "selected_routes": routes,
            "routes_observed": route_summary(decisions, additions),
            **summarize(decisions, references, additions, routes),
        }
        with (args.output / f"{name}.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(name, routes, report["metrics"], flush=True)


if __name__ == "__main__":
    main()
