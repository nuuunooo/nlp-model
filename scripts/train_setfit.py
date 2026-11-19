"""Fine-tune multilingual E5 with SetFit on reviewed descriptions or V2 JSONL splits."""

import argparse
from contextlib import nullcontext
import csv
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, Path as ZipPath, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine import MODEL_MIN_CONF, catalog, normalize
from src.setfit_classifier import ENCODER, ENCODER_REVISION, e5_input, score_codes
from scripts.setfit_v2 import metrics, read_split, select_thresholds, targets_for

MIN_TRAIN_PER_OUTCOME = 8


def csv_reviews(raw_path, gold_path):
    with raw_path.open(encoding="utf-8-sig", newline="") as file:
        tickets = {row["ticket_id"]: row for row in csv.DictReader(file)}
    with gold_path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            status = row["annotation_status"]
            if status not in {"labeled", "clear"}:
                continue
            ticket = tickets[row["ticket_id"]]
            codes = set(filter(None, (code.strip() for code in row["gold_codes"].split("|"))))
            if bool(codes) != (status == "labeled"):
                raise ValueError(f"Label and annotation status disagree for ticket {row['ticket_id']}")
            yield ticket["vendor_id"], normalize(ticket["description"]), codes


def database_reviews():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL or supply --raw and --gold")
    import psycopg

    with psycopg.connect(url) as conn:
        rows = conn.execute("""
            SELECT t.vendor_id, t.description, n.clean_text, q.proposed_codes
            FROM public.nlp_review_queue q
            JOIN public.nlp_ticket_text n ON n.ticket_id = q.ticket_id
            JOIN public.tickets t ON t.id = q.ticket_id
            WHERE q.status = 'confirmed' AND lower(coalesce(t.status, '')) <> 'void'
              AND NOT EXISTS (
                SELECT 1 FROM public.nlp_violation_taxonomy v
                WHERE v.code = ANY(q.proposed_codes) AND NOT v.is_active
              )
            ORDER BY t.id
        """)
        for vendor, description, reviewed_text, codes in rows:
            if normalize(description) == reviewed_text:
                yield vendor, reviewed_text, set(codes)


def grouped_rows(reviews, taxonomy):
    """Keep each vendor and normalized description on one side of the holdout."""
    parents = {}

    def root(key):
        parents.setdefault(key, key)
        while key != parents[key]:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    by_text = {}
    for vendor, text, codes in reviews:
        if not codes.issubset(taxonomy):
            raise ValueError(f"Labels outside the action taxonomy: {sorted(codes - taxonomy.keys())}")
        if not text:
            continue
        if not str(vendor or "").strip():
            raise ValueError("Every reviewed description needs a vendor ID for grouped evaluation")
        vendor_key = ("vendor", str(vendor).strip())
        text_key = ("text", text)
        parents[root(vendor_key)] = root(text_key)
        if text in by_text and by_text[text] != codes:
            raise ValueError("Identical normalized descriptions have conflicting reviews")
        by_text[text] = codes
    return [(text, codes, root(("text", text))[1]) for text, codes in by_text.items()]


def fit_model(texts, targets, codes, encoder_dir, work):
    from datasets import Dataset
    from sentence_transformers import SentenceTransformer
    from setfit import SetFitModel, Trainer, TrainingArguments
    from sklearn.linear_model import LogisticRegression
    from sklearn.multioutput import MultiOutputClassifier
    from transformers import set_seed

    set_seed(42)
    body = SentenceTransformer(
        str(encoder_dir.resolve()) if encoder_dir else ENCODER,
        revision=None if encoder_dir else ENCODER_REVISION,
        local_files_only=encoder_dir is not None,
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True},
    )
    model = SetFitModel(
        model_body=body,
        model_head=MultiOutputClassifier(LogisticRegression(max_iter=1000, class_weight="balanced")),
        multi_target_strategy="multi-output",
        normalize_embeddings=True,
        labels=codes,
    )
    dataset = Dataset.from_dict({"text": [e5_input(text) for text in texts], "label": targets.tolist()})
    args = TrainingArguments(
        output_dir=str(work / "checkpoints"), batch_size=8, num_epochs=1, max_steps=250,
        save_strategy="no", report_to=[], seed=42,
    )
    Trainer(model=model, args=args, train_dataset=dataset).train()
    return model


def save_model(model, directory):
    model.save_pretrained(str(directory))
    # SetFit's generated card can contain examples from the training dataset.
    (directory / "README.md").write_text("# Local market violation classifier\n", encoding="utf-8")


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def train_v2(dataset, output, encoder_dir):
    import numpy as np

    if output.exists():
        raise FileExistsError(f"Use a new model directory: {output}")
    taxonomy, _ = catalog()
    codes = list(taxonomy)
    if len(codes) != 29:
        raise ValueError("The V2 catalog must have 29 distinct categories")
    output.parent.mkdir(parents=True, exist_ok=True)
    source = nullcontext(dataset) if dataset.is_dir() else ZipFile(dataset)
    with source as opened, TemporaryDirectory(dir=output.parent) as work:
        root = opened if dataset.is_dir() else ZipPath(opened)
        seen_texts = set()
        fitting, train_hash = read_split(root, "train_fit", codes, seen_texts)
        validation, validation_hash = read_split(root, "validation", codes, seen_texts)
        targets = targets_for(fitting, codes)
        positives = targets.sum(axis=0)
        negatives = len(fitting) - positives
        unsupported = [
            code for code, pos, neg in zip(codes, positives, negatives)
            if min(pos, neg) < MIN_TRAIN_PER_OUTCOME
        ]
        if unsupported:
            raise ValueError(f"Insufficient training support: {unsupported}")

        work = Path(work)
        print(f"Fitting {len(codes)} categories on {len(fitting)} train_fit descriptions.", flush=True)
        model = fit_model([row["description"] for row in fitting], targets.astype(int), codes, encoder_dir, work)
        print(f"Selecting thresholds on {len(validation)} validation descriptions.", flush=True)
        val_scores = score_codes(model, [row["description"] for row in validation])
        thresholds = np.array(select_thresholds(validation, val_scores, codes))
        thresholds.setflags(write=False)
        staged = work / "model"
        save_model(model, staged)
        write_json(staged / "thresholds.json", {
            "selection_split": "validation",
            "objective": "Maximize per-category F1 on known labels, preferring higher thresholds on ties",
            "thresholds": dict(zip(codes, thresholds.tolist())),
        })

        test, test_hash = read_split(root, "test", codes, seen_texts)
        print(f"Evaluating frozen thresholds once on {len(test)} test descriptions.", flush=True)
        test_scores = score_codes(model, [row["description"] for row in test])
        write_json(staged / "evaluation.json", {
            "dataset": dataset.name,
            "split_sha256": {"train_fit": train_hash, "validation": validation_hash, "test": test_hash},
            "encoder": ENCODER,
            "encoder_revision": ENCODER_REVISION if encoder_dir is None else None,
            "local_encoder": str(encoder_dir.resolve()) if encoder_dir else None,
            "seed": 42,
            "train_rows": len(fitting),
            "train_support": {
                code: {"positive": int(pos), "negative": int(neg)}
                for code, pos, neg in zip(codes, positives, negatives)
            },
            "validation": metrics(validation, val_scores >= thresholds, codes),
            "test": metrics(test, test_scores >= thresholds, codes),
        })
        staged.rename(output)
    print(f"Saved trained model, validation thresholds and test metrics to {output}", flush=True)


def train(rows, taxonomy, output, encoder_dir):
    if output.exists():
        raise FileExistsError(f"Use a new model directory: {output}")
    if len(rows) < 2 * MIN_TRAIN_PER_OUTCOME + 2:
        raise ValueError(f"Only {len(rows)} distinct reviewed descriptions. Need at least "
                         "8 positive and 8 negative training examples per code plus a holdout.")
    import numpy as np
    from sklearn.metrics import classification_report
    from sklearn.model_selection import GroupShuffleSplit

    texts, labels, groups = zip(*rows)
    if len(set(groups)) < 2:
        raise ValueError("Need at least two independent groups of reviewed descriptions")
    codes = sorted(taxonomy)
    target = np.array([[int(code in row) for code in codes] for row in labels])
    train_idx, test_idx = next(GroupShuffleSplit(test_size=0.2, random_state=42).split(texts, groups=groups))
    positive = target[train_idx].sum(axis=0)
    heldout_positive = target[test_idx].sum(axis=0)
    supported = (
        (positive >= MIN_TRAIN_PER_OUTCOME)
        & (len(train_idx) - positive >= MIN_TRAIN_PER_OUTCOME)
        & (heldout_positive > 0)
        & (heldout_positive < len(test_idx))
    )
    if not supported.any():
        raise ValueError("No code has sufficient positive and negative examples in the grouped split")
    fitted_codes = [code for code, keep in zip(codes, supported) if keep]
    y_train = target[train_idx][:, supported]
    y_test = target[test_idx][:, supported]

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as work:
        work = Path(work)
        model = fit_model([texts[i] for i in train_idx], y_train, fitted_codes, encoder_dir, work)
        predictions = score_codes(model, [texts[i] for i in test_idx]) >= MODEL_MIN_CONF
        clear = np.array([not labels[i] for i in test_idx])
        # With a single code, sklearn's report expects explicit binary labels.
        report_options = ({"labels": [1], "target_names": fitted_codes}
                          if len(fitted_codes) == 1 else {"target_names": fitted_codes})
        report = {
            "train_rows": len(train_idx),
            "held_out_rows": len(test_idx),
            "held_out_clear_rows": int(clear.sum()),
            "clear_false_alarms": int(predictions[clear].any(axis=1).sum()),
            "suggestion_threshold": MODEL_MIN_CONF,
            "unsupported_codes": sorted(set(codes) - set(fitted_codes)),
            "supported_code_metrics": classification_report(
                y_test, predictions, output_dict=True, zero_division=0, **report_options
            ),
        }
        staged = work / "model"
        save_model(model, staged)
        write_json(staged / "evaluation.json", report)
        staged.rename(output)
    print(f"Saved trained SetFit artifact and held-out metrics to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw", type=Path, help="CSV of ticket_id, vendor_id and description")
    parser.add_argument("--gold", type=Path, help="CSV of ticket_id, gold_codes and annotation_status")
    parser.add_argument("--dataset", type=Path, help="V2 archive or directory with train_fit, validation and test JSONL")
    parser.add_argument("--encoder-dir", type=Path, help="Optional local multilingual-e5-small checkpoint")
    args = parser.parse_args()
    if bool(args.raw) != bool(args.gold):
        parser.error("--raw and --gold must be supplied together")
    if args.dataset and args.raw:
        parser.error("--dataset cannot be combined with --raw and --gold")
    output = args.output.resolve()
    try:
        if args.dataset:
            train_v2(args.dataset, output, args.encoder_dir)
        else:
            taxonomy, _ = catalog()
            reviews = csv_reviews(args.raw, args.gold) if args.raw else database_reviews()
            train(grouped_rows(reviews, taxonomy), taxonomy, output, args.encoder_dir)
    except (ValueError, FileNotFoundError, FileExistsError, KeyError, BadZipFile) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
