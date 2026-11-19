"""Evaluate automatic recommendations with only descriptions as inference input."""

import argparse
import csv
import io
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine import analyze_ticket, catalog, normalize
try:
    from src.incidents import inference_inputs
except ModuleNotFoundError as exc:
    if exc.name != 'src.incidents':
        raise
    def inference_inputs(description, normalizer):
        return [normalizer(description)]
from src.setfit_classifier import SetFitClassifier, score_codes


def evaluate(dataset, split, model_dir, output, cache, purpose="development_regression"):
    import numpy as np
    from sklearn.metrics import precision_recall_fscore_support

    if output.exists():
        raise FileExistsError(f"Use a new report path: {output}")
    source_hashes = {name:sha256(Path(name).read_bytes()).hexdigest() for name in (
        "src/engine.py","src/description_evidence.py","src/incidents.py","src/breach_evidence.py",
        "src/setfit_classifier.py","src/reweigh.py","src/llm.py","config/evidence_policy.json","config/lexicon.csv","config/taxonomy.csv",
    ) if Path(name).is_file()}
    standalone = dataset.suffix.lower() in {".jsonl", ".csv"}
    if standalone:
        payload = dataset.read_bytes()
    else:
        with ZipFile(dataset) as archive:
            payload = archive.read(f"{split}.jsonl")
    if dataset.suffix.lower() == ".csv":
        raw_rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline="")))
        rows = [{"scenario_id":row["record_id"], "description":row["description"],
                 "language":"unspecified", "expected_decision":row["expected_decision"],
                 "expected_codes":None if row["expected_decision"] == "abstain" else list(filter(None, row["gold_codes"].split("|")))}
                for row in raw_rows]
    else:
        rows = [json.loads(line) for line in payload.splitlines()]
    taxonomy, lexicon = catalog()
    codes = json.loads((model_dir / "config_setfit.json").read_text(encoding="utf-8"))["labels"]
    thresholds_payload = (model_dir / "thresholds.json").read_bytes()
    thresholds = json.loads(thresholds_payload)["thresholds"]
    if set(codes) != set(taxonomy) or set(thresholds) != set(codes):
        raise ValueError("Model, thresholds and taxonomy must use the same categories")
    if len({(row["scenario_id"], row["language"]) for row in rows}) != len(rows):
        raise ValueError("Evaluation record IDs must be unique")
    for row in rows:
        expected = row["expected_codes"]
        decision = "abstain" if expected is None else "accept" if expected else "clear"
        if (row["expected_decision"] != decision or expected is not None and
                (len(expected) != len(set(expected)) or not set(expected).issubset(taxonomy))):
            raise ValueError("Invalid evaluation labels or decision")
    groups = [inference_inputs(row["description"], normalize) for row in rows]
    texts = list(dict.fromkeys(text for group in groups for text in group))
    positions = {value:index for index,value in enumerate(texts)}
    provenance = {
        "split_sha256": sha256(payload).hexdigest(),
        "thresholds_sha256": sha256(thresholds_payload).hexdigest(),
        "model_sha256": sha256((model_dir / "model.safetensors").read_bytes()).hexdigest(),
        "head_sha256": sha256((model_dir / "model_head.pkl").read_bytes()).hexdigest(),
        "codes": codes,
        "inference_artifacts_sha256":{str(p.relative_to(model_dir)):sha256(p.read_bytes()).hexdigest()
                                      for p in model_dir.rglob('*') if p.is_file()
                                      and p.name not in {'README.md','evaluation.json','model.safetensors','model_head.pkl','thresholds.json'}},
        "scorer_sha256":source_hashes['src/setfit_classifier.py'],
        "inference_layout_sha256":sha256(json.dumps(groups, ensure_ascii=False).encode()).hexdigest(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        with np.load(cache, allow_pickle=False) as saved:
            prior = json.loads(str(saved["provenance"]))
            if any(prior.get(key) != provenance[key] for key in provenance if key != "inference_layout_sha256"):
                raise ValueError("Cached probabilities do not match this dataset and frozen model")
            if prior == provenance:
                scores = saved["scores"]
                missing = []
            elif "texts" in saved:
                lookup = {str(t):s for t,s in zip(saved["texts"], saved["scores"])}
                missing = [t for t in texts if t not in lookup]
            else:
                raise ValueError("Use a new cache path for changed inference inputs")
        if missing:
            classifier = SetFitClassifier(model_dir, taxonomy)
            print(f"Scoring {len(missing)} new incident contexts; reusing matching frozen-model scores.", flush=True)
            lookup.update(zip(missing, score_codes(classifier.model, missing)))
        else:
            classifier = SetFitClassifier.__new__(SetFitClassifier)
            classifier.model = SimpleNamespace(labels=codes)
            classifier.thresholds = thresholds
        if prior != provenance:
            scores = np.array([lookup[t] for t in texts])
            np.savez_compressed(cache, scores=scores, texts=np.array(texts), provenance=json.dumps(provenance))
    else:
        classifier = SetFitClassifier(model_dir, taxonomy)
        print(f"Scoring {len(texts)} {split} descriptions with the frozen model.", flush=True)
        scores = score_codes(classifier.model, texts)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, scores=scores, texts=np.array(texts), provenance=json.dumps(provenance))
    if scores.shape != (len(texts), len(codes)) or not np.isfinite(scores).all():
        raise ValueError("Invalid cached model probabilities")
    decisions = []
    for index, row in enumerate(rows):
        # Reuse the frozen probabilities through the normal classifier entry point.
        with patch("src.setfit_classifier.score_codes", side_effect=lambda model, requested:
                   scores[[positions[value] for value in requested]]):
            result, findings = analyze_ticket(
                {"ticket_id":row["scenario_id"], "description":row["description"]},
                taxonomy, lexicon, classifier,
            )
        expected = row["expected_codes"]
        predicted = sorted(finding["code"] for finding in findings)
        decisions.append({
            "scenario_id":row["scenario_id"], "language":row["language"],
            "description":row["description"], "expected_codes":expected,
            "expected_decision":row["expected_decision"], "predicted_codes":predicted,
            "missing_codes":sorted(set(expected or []) - set(predicted)),
            "unrelated_codes":sorted(set(predicted) - set(expected or [])),
            "status":result["status"], "reason":result["review_reason"],
            "sources":{finding["code"]:finding["source"] for finding in findings},
        })

    def metrics(selected):
        known = [row for row in selected if row["expected_codes"] is not None]
        truth = np.array([[code in row["expected_codes"] for code in codes] for row in known], dtype=bool)
        predicted = np.array([[code in row["predicted_codes"] for code in codes] for row in known], dtype=bool)
        precision, recall, f1, support = precision_recall_fscore_support(
            truth, predicted, average=None, zero_division=0)
        micro = precision_recall_fscore_support(truth, predicted, average="micro", zero_division=0)
        clear = [row for row in selected if row["expected_decision"] == "clear"]
        ambiguous = [row for row in selected if row["expected_decision"] == "abstain"]
        pairs = [row for row in known if len(row["expected_codes"]) > 1]
        return {
            "rows":len(selected), "known_rows":len(known),
            "micro_precision":float(micro[0]), "micro_recall":float(micro[1]), "micro_f1":float(micro[2]),
            "macro_f1":float(f1.mean()),
            "exact_label_set_matches":sum(row["expected_codes"] == row["predicted_codes"]
                                           or set(row["expected_codes"]) == set(row["predicted_codes"])
                                           for row in known),
            "clear_rows":len(clear), "clear_rows_with_actions":sum(bool(row["predicted_codes"]) for row in clear),
            "unclear_rows":len(ambiguous), "unclear_rows_with_actions":sum(bool(row["predicted_codes"]) for row in ambiguous),
            "pair_rows":len(pairs), "pair_rows_both_correct":sum(set(row["expected_codes"]) == set(row["predicted_codes"]) for row in pairs),
            "per_category":{
                code:{"precision":float(precision[i]),"recall":float(recall[i]),"f1":float(f1[i]),
                      "support":int(support[i]),"false_positives":int((~truth[:,i] & predicted[:,i]).sum()),
                      "false_negatives":int((truth[:,i] & ~predicted[:,i]).sum())}
                for i, code in enumerate(codes)
            },
        }

    report = {
        "dataset":str(dataset), "split":split, "model":str(model_dir),
        "purpose":purpose,
        "method":"Only description is passed to inference. Labels, language and scenarios are evaluation metadata. Frozen model probabilities and thresholds are reused through the normal classifier and ticket analysis.",
        "interpretation":(
            "Standalone labeled benchmark. Dataset provenance must be assessed separately."
            if standalone else
            "Synthetic scenario evaluation on previously used development and regression splits."
        ),
        "provenance":provenance,
        "source_sha256":source_hashes,
        "metrics":metrics(decisions),
        "by_language":{lang:metrics([row for row in decisions if row["language"] == lang])
                       for lang in sorted({row["language"] for row in decisions})},
        "decisions":decisions,
    }
    if any(sha256(Path(name).read_bytes()).hexdigest() != expected for name,expected in source_hashes.items()):
        raise RuntimeError("Runtime changed during evaluation; no report saved")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({key:value for key,value in report["metrics"].items() if key != "per_category"}, indent=2))
    print(f"Saved {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=("validation","test"), required=True)
    parser.add_argument("--model", type=Path, default=Path("models/setfit-e5-synthetic-v2"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.dataset, args.split, args.model.resolve(), args.output, args.scores)


if __name__ == "__main__":
    main()
