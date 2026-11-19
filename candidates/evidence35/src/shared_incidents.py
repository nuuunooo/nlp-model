"""Offline candidate using one incident evidence decision for every category."""

from collections import defaultdict
from dataclasses import dataclass
from hashlib import file_digest
from pathlib import Path
import re

import numpy as np

from .engine import CLEAN_RE, JUNK_RE, ROOT, catalog, normalize
from .evidence_verifier import EvidenceVerifier, STATES
from .incidents import UNCERTAIN, incident_spans
from .setfit_classifier import SetFitClassifier, e5_input
from .structured_evidence import structured_state


PIPELINE_VERSION = "3.5-shared-incidents"
CANDIDATES_PER_INCIDENT = 3
HYPOTHETICAL = re.compile(r"^(?:if|kung|halimbawa|hypothetically|for example)\b")


@dataclass(frozen=True)
class EvidenceDecision:
    code: str
    state: str
    reason: str
    evidence: str


class SharedIncidentPipeline:
    def __init__(self, model_dir, verifier_dir):
        self.taxonomy, _ = catalog()
        self.verifier = EvidenceVerifier(verifier_dir)
        if self.verifier.codes != list(self.taxonomy):
            raise ValueError("Evidence verifier categories differ from the policy catalog")
        expected_policy = self.verifier.metadata.get("policy_sha256")
        if expected_policy:
            with (ROOT / "config/taxonomy.csv").open("rb") as handle:
                if file_digest(handle, "sha256").hexdigest() != expected_policy:
                    raise ValueError("Evidence verifier policy catalog has changed")
        model_dir = Path(model_dir)
        for name, expected in self.verifier.metadata["encoder_identity"].items():
            with (model_dir / name).open("rb") as handle:
                if file_digest(handle, "sha256").hexdigest() != expected:
                    raise ValueError(f"Evidence encoder has changed: {name}")
        self.model = SetFitClassifier(model_dir, self.taxonomy).model
        if set(self.model.labels) != set(self.taxonomy):
            raise ValueError("Category classifier does not cover the full policy catalog")
        self.max_length = min(self.model.model_body.max_seq_length, self.verifier.metadata["max_sequence_length"])

    def analyze_many(self, descriptions):
        groups = [self.extract(description) for description in descriptions]
        eligible = list(dict.fromkeys(incident.context for group in groups for incident in group
                                     if self.eligible(incident)))
        nominations, vectors = self.nominate(eligible)
        pending = []
        output = [defaultdict(list) for _ in groups]
        for record, group in enumerate(groups):
            for index, incident in enumerate(group):
                if not self.eligible(incident):
                    continue
                for code in nominations.get(incident.context, ()):
                    parsed = structured_state(code, incident)
                    if parsed is not None:
                        state, reason = parsed
                        output[record][index].append(EvidenceDecision(code, state, reason, incident.context))
                    else:
                        pending.append((record, index, incident.context, code))
        pairs = [{"description": context, "target_code": code} for _, _, context, code in pending]
        if pairs:
            probabilities = self.verifier.probabilities(pairs, vectors)
            for (record, index, context, code), scores in zip(pending, probabilities, strict=True):
                state, reason = self.learned_state(scores)
                output[record][index].append(EvidenceDecision(code, state, reason, context))
        return [self.result(group, decisions) for group, decisions in zip(groups, output, strict=True)]

    @staticmethod
    def extract(description):
        clean = normalize(description)
        if not clean or CLEAN_RE.fullmatch(clean.rstrip(" ,;.!?")) or JUNK_RE.search(clean):
            return []
        return incident_spans(description, normalize)

    @staticmethod
    def eligible(incident):
        return (not incident.blocked and not incident.is_requirement and "?" not in incident.context
                and not UNCERTAIN.search(incident.context) and not HYPOTHETICAL.search(incident.text))

    def nominate(self, contexts):
        if not contexts:
            return {}, {}
        body = self.model.model_body
        queries = [e5_input(context) for context in contexts]
        token_ids = body.tokenizer(queries, truncation=False, padding=False)["input_ids"]
        valid = [context for context, ids in zip(contexts, token_ids, strict=True) if len(ids) <= self.max_length]
        if not valid:
            return {}, {}
        embeddings = self.model.encode([e5_input(context) for context in valid], show_progress_bar=False)
        scores = np.stack(self.model.model_head.predict_proba(embeddings), axis=1)[:, :, 1]
        nominations = {
            context: [self.model.labels[index] for index in np.argsort(-row, kind="stable")[:CANDIDATES_PER_INCIDENT]]
            for context, row in zip(valid, scores, strict=True)
        }
        # The verifier uses unit vectors, even if SetFit's saved category head uses raw embeddings.
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        vectors = dict(zip(valid, embeddings / np.maximum(norms, 1e-12), strict=True))
        return nominations, vectors

    def learned_state(self, scores):
        state = STATES[int(np.argmax(scores))]
        if state != "insufficient":
            cutoff = self.verifier.cutoff if state == "supported" else self.verifier.metadata.get("compliance_cutoff")
            if cutoff is None or max(scores) < cutoff:
                return "insufficient", f"{state}_below_validated_cutoff"
        return state, "learned_policy_evidence"

    def result(self, group, decisions):
        by_category = {}
        for index, _ in enumerate(group):
            for decision in decisions[index]:
                if decision.state == "supported":
                    by_category.setdefault(decision.code, {
                        "code": decision.code, "evidence": decision.evidence,
                        "reason": decision.reason, "action": self.taxonomy[decision.code]["action_template_en"],
                    })
        return {
            "findings": list(by_category.values()),
            "incidents": [{
                "observation": incident.text, "context": incident.context,
                "reason": incident.reason or (
                    "not_an_observation" if not self.eligible(incident) else
                    "scored" if decisions[index] else "context_exceeds_model_limit"
                ),
                "decisions": [vars(decision) for decision in decisions[index]],
            } for index, incident in enumerate(group)],
        }
