"""Read the fixed synthetic splits and evaluate frozen category thresholds."""

from hashlib import sha256
import json

from src.engine import normalize


LANGUAGES = ("fil", "en", "taglish")


def read_split(root, name, codes, seen_texts):
    filename = f"{name}.jsonl"
    data = (root / filename).read_bytes()
    rows = []
    for number, line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        row = json.loads(line)
        text = normalize(row["description"])
        labels = row["expected_codes"]
        location = f"{filename}:{number}"
        if not text or text in seen_texts:
            raise ValueError(f"{location}: empty or duplicate normalized description")
        if labels is not None and (
            not isinstance(labels, list) or any(code not in codes for code in labels)
        ):
            raise ValueError(f"{location}: invalid category labels")
        if name == "train_fit":
            if labels is None:
                raise ValueError(f"{location}: abstention rows cannot be used for fitting")
        else:
            expected_decision = "abstain" if labels is None else "accept" if labels else "clear"
            if (row["split"] != name or row["language"] not in LANGUAGES
                    or row["expected_decision"] != expected_decision):
                raise ValueError(f"{location}: inconsistent evaluation metadata")
        seen_texts.add(text)
        rows.append({**row, "description": text})
    if not rows:
        raise ValueError(f"{filename}: split is empty")
    return rows, sha256(data).hexdigest()


def targets_for(rows, codes):
    import numpy as np

    return np.array([[code in (row["expected_codes"] or ()) for code in codes] for row in rows])


def select_thresholds(rows, scores, codes):
    import numpy as np
    from sklearn.metrics import precision_recall_curve

    known = np.array([row["expected_codes"] is not None for row in rows])
    targets = targets_for(rows, codes)[known]
    if not known.any() or not targets.any(axis=0).all() or targets.all(axis=0).any():
        raise ValueError("Validation must contain positive and negative labels for every category")
    thresholds = []
    for index in range(len(codes)):
        precision, recall, candidates = precision_recall_curve(targets[:, index], scores[known, index])
        total = precision[:-1] + recall[:-1]
        f1 = np.divide(2 * precision[:-1] * recall[:-1], total, out=np.zeros_like(total), where=total > 0)
        # The candidates are ascending. Prefer the higher cutoff when F1 ties.
        thresholds.append(float(candidates[len(candidates) - 1 - f1[::-1].argmax()]))
    return thresholds


def metrics(rows, predictions, codes):
    import numpy as np

    def counts(targets, predicted):
        tp = int((targets & predicted).sum())
        fp = int((~targets & predicted).sum())
        fn = int((targets & ~predicted).sum())
        return {
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0,
            "support": tp + fn,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
        }

    def summarize(selected):
        known = selected & (decisions != "abstain")
        clear = selected & (decisions == "clear")
        ambiguous = selected & (decisions == "abstain")
        positive = selected & (decisions == "accept")
        known_targets, known_predictions = targets[known], predictions[known]
        per_category = {
            code: counts(known_targets[:, i], known_predictions[:, i])
            for i, code in enumerate(codes)
        }
        return {
            "rows": int(selected.sum()),
            "labeled_rows": int(known.sum()),
            "micro": counts(known_targets, known_predictions),
            "macro_f1": float(np.mean([category["f1"] for category in per_category.values()])),
            "exact_label_set_matches": int((known_targets == known_predictions).all(axis=1).sum()),
            "clear_rows": int(clear.sum()),
            "clear_rows_with_predictions": int((clear & emitted).sum()),
            "expected_abstention_rows": int(ambiguous.sum()),
            "abstentions_on_expected_abstention_rows": int((ambiguous & ~emitted).sum()),
            "positive_rows_without_predictions": int((positive & ~emitted).sum()),
            "per_category": per_category,
        }

    targets = targets_for(rows, codes)
    decisions = np.array([row["expected_decision"] for row in rows])
    languages = np.array([row["language"] for row in rows])
    emitted = predictions.any(axis=1)
    return {
        **summarize(np.ones(len(rows), dtype=bool)),
        "by_language": {language: summarize(languages == language) for language in LANGUAGES},
    }
