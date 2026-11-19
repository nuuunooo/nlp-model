from datetime import datetime
import unittest
from unittest.mock import MagicMock, Mock, patch

from scripts.train_setfit import grouped_rows
from src.db_runner import write_batch
from src.engine import analyze_ticket, catalog, summarize_sections
from src.setfit_classifier import SetFitClassifier


class SetFitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy, self.lexicon = catalog()
        self.classifier = SetFitClassifier.__new__(SetFitClassifier)
        self.classifier.model = Mock(labels=["WeightMeasures", "Sanitation"])
        self.ticket = {
            "ticket_id": 15,
            "vendor_id": 8,
            "section_id": 2,
            "ticket_type": "Ticket",
            "issued_at": "2026-10-01T07:30:00+08:00",
            "description": "May daya sa panukat at uncovered yung paninda",
        }

    def test_supported_multilabel_suggestions_automatically_drive_action(self):
        # Stub the classifier's numerical output to exercise routing without model weights.
        scores = MagicMock(shape=(1, 2, 2))
        scores.__getitem__.return_value = [[0.92, 0.83]]
        self.classifier.model.predict_proba.return_value = scores
        clean, mentions = analyze_ticket(self.ticket, self.taxonomy, self.lexicon, self.classifier)
        self.classifier.model.predict_proba.assert_called_once_with(
            ["query: may daya sa panukat at uncovered yung paninda"],
            as_numpy=True, show_progress_bar=False,
        )
        self.assertEqual(clean["pipeline_version"], "3.3.0-description-only")
        self.assertEqual(clean["status"], "labeled")
        self.assertEqual({row["code"] for row in mentions}, {"WeightMeasures", "Sanitation"})
        self.assertTrue(all(row["review_status"] == "accepted" for row in mentions))

        sections = [{"section_id": 2, "section_name": "Fish & Seafood"}]
        anchor = datetime.fromisoformat(self.ticket["issued_at"])
        before = summarize_sections(mentions, [], self.taxonomy, sections, anchor=anchor)[0]
        self.assertIn("Compare actual product weights", before["recommended_action"])
        after = summarize_sections(
            [mentions[0]], [], self.taxonomy, sections, anchor=anchor
        )[0]
        self.assertIn("Compare actual product weights", after["recommended_action"])
        self.assertEqual(after["pattern_confidence"], "Unknown")

    @patch("src.setfit_classifier.score_codes", return_value=[[0.7799, 0.78]])
    def test_threshold_applied_before_rounding(self, score):
        self.assertEqual(self.classifier.predict("clean text"), [{"code": "Sanitation", "confidence": 0.78}])

    @patch("src.setfit_classifier.score_codes", return_value=[[0.73, 0.83]])
    def test_category_cutoffs_control_automatic_proposals(self, score):
        self.classifier.thresholds = {"WeightMeasures": 0.70, "Sanitation": 0.85}
        base, mentions = analyze_ticket(self.ticket, self.taxonomy, self.lexicon, self.classifier)
        self.assertEqual(base["status"], "labeled")
        self.assertEqual([(m["code"], m["review_status"]) for m in mentions], [
            ("WeightMeasures", "accepted"),
        ])

    def test_worker_proposes_action_without_creating_user_tasks(self):
        ticket = dict(self.ticket, updated_at=datetime.fromisoformat(self.ticket["issued_at"]))
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        with patch("src.setfit_classifier.score_codes", return_value=[[0.92,0.83]]):
            self.assertEqual(write_batch(conn,[ticket],self.taxonomy,self.lexicon,self.classifier,None),(1,2,0))
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertFalse(any("INSERT INTO public.nlp_review_queue" in sql for sql in statements))
        self.assertFalse(any("nlp_verified_reweighs" in sql for sql in statements))
        self.assertTrue(any("INSERT INTO public.nlp_violation_mentions" in sql for sql in statements))

    def test_training_groups_link_vendors_and_shared_descriptions(self):
        rows = grouped_rows([
            ("vendor-1", "phrase 1", {"WeightMeasures"}),
            ("vendor-1", "phrase 2", {"Sanitation"}),
            ("vendor-2", "phrase 2", {"Sanitation"}),
            ("vendor-2", "phrase 3", set()),
            ("vendor-3", "phrase 4", set()),
        ], self.taxonomy)
        groups = {text: group for text, _, group in rows}
        self.assertEqual(len(groups), 4)
        self.assertEqual(groups["phrase 1"], groups["phrase 3"])
        self.assertNotEqual(groups["phrase 1"], groups["phrase 4"])
