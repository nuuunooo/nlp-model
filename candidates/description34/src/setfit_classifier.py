"""Local multilabel SetFit inference for the recommendation worker."""

import json
from pathlib import Path

from .engine import MODEL_MIN_CONF, RULE_PIPELINE_VERSION

ENCODER = "intfloat/multilingual-e5-small"
ENCODER_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"


def e5_input(clean_text):
    return f"query: {clean_text}"


def score_codes(model, texts):
    # MultiOutputClassifier returns negative and positive probabilities per label.
    scores = model.predict_proba(
        [e5_input(text) for text in texts], as_numpy=True, show_progress_bar=False
    )
    if scores.shape != (len(texts), len(model.labels), 2):
        raise ValueError("SetFit output does not match the saved violation labels")
    return scores[:, :, 1]


class SetFitClassifier:
    score_all_descriptions = True
    pipeline_version = RULE_PIPELINE_VERSION
    thresholds = None

    def __init__(self, model_dir, taxonomy):
        path = Path(model_dir).resolve()
        for filename in ("config_setfit.json", "model_head.pkl", "modules.json", "model.safetensors"):
            if not (path / filename).is_file():
                raise FileNotFoundError(f"Missing trained SetFit artifact: {path / filename}")
        from setfit import SetFitModel

        # The sklearn head is serialized with pickle. Use a trusted local model only.
        self.model = SetFitModel.from_pretrained(str(path), device="cpu", local_files_only=True)
        codes = self.model.labels
        if not codes or len(codes) != len(set(codes)) or not set(codes).issubset(taxonomy):
            raise ValueError("SetFit labels must be distinct codes from the action taxonomy")
        threshold_file = path / "thresholds.json"
        if threshold_file.is_file():
            thresholds = json.loads(threshold_file.read_text(encoding="utf-8"))["thresholds"]
            if (not isinstance(thresholds, dict) or set(thresholds) != set(codes)
                    or any(type(value) not in (int, float) or not 0 <= value <= 1
                           for value in thresholds.values())):
                raise ValueError("SetFit thresholds must match the saved labels and be between 0 and 1")
            self.thresholds = thresholds
        score_codes(self.model, ["inspection model startup check"])

    @property
    def uses_category_thresholds(self):
        return self.thresholds is not None

    def predict(self, clean_text, threshold=None):
        cutoffs = self.thresholds if threshold is None and self.uses_category_thresholds else {}
        fallback = MODEL_MIN_CONF if threshold is None else threshold
        scores = score_codes(self.model, [clean_text])[0]
        return [
            {"code": code, "confidence": round(float(score), 3)}
            for code, score in zip(self.model.labels, scores)
            if score >= cutoffs.get(code, fallback)
        ]

    def predict_many(self, clean_texts, threshold=None):
        if not clean_texts:
            return []
        # Retain the single-text path for compatible classifier stubs and callers.
        if len(clean_texts) == 1:
            return [self.predict(clean_texts[0], threshold)]
        cutoffs = self.thresholds if threshold is None and self.uses_category_thresholds else {}
        fallback = MODEL_MIN_CONF if threshold is None else threshold
        rows = score_codes(self.model, clean_texts)
        return [[{"code":code, "confidence":round(float(score), 3)}
                 for code, score in zip(self.model.labels, row)
                 if score >= cutoffs.get(code, fallback)] for row in rows]
