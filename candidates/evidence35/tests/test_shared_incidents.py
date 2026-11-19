from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from scripts.train_evidence_verifier import contrastive_examples
from src.engine import catalog
from src.shared_incidents import SharedIncidentPipeline
from src.structured_evidence import structured_state


class SharedIncidentTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = SharedIncidentPipeline.__new__(SharedIncidentPipeline)
        self.pipeline.taxonomy, _ = catalog()
        self.pipeline.verifier = SimpleNamespace(
            cutoff=.95, metadata={"compliance_cutoff": .96}, probabilities=Mock()
        )

    def test_same_learned_decision_accepts_an_unfamiliar_wording_and_separates_states(self):
        self.pipeline.nominate = lambda texts: ({text: ["Sanitation"] for text in texts}, {})
        self.pipeline.verifier.probabilities.return_value = [
            [.97, .01, .02], [.02, .97, .01], [.10, .65, .25],
        ]
        results = self.pipeline.analyze_many(["description alpha", "description beta", "description gamma"])
        self.assertEqual([row["incidents"][0]["decisions"][0]["state"] for row in results],
                         ["supported", "compliant", "insufficient"])
        self.assertEqual([bool(row["findings"]) for row in results], [True, False, False])

    def test_uncertain_followup_blocks_only_its_incident(self):
        self.pipeline.nominate = lambda texts: ({text: ["WeightMeasures", "Stall Management"] for text in texts}, {})
        self.pipeline.verifier.probabilities.return_value = [[.02, .01, .97]]
        description = (
            "Walang fire extinguisher, required to. This was not confirmed. "
            "Separately, 900g ang lumalabas sa scale ng vendor kapag nilagay ang 1kg test weight."
        )
        result = self.pipeline.analyze_many([description])[0]
        self.assertEqual([finding["code"] for finding in result["findings"]], ["WeightMeasures"])
        self.assertEqual(result["incidents"][0]["reason"], "unconfirmed_followup")

    def test_scale_test_compares_the_reference_and_display_in_compatible_units(self):
        for reading, expected in [("900g", "supported"), ("1000g", "compliant"), ("1100g", "supported")]:
            with self.subTest(reading=reading):
                incident, = self.pipeline.extract(
                    f"{reading} ang lumalabas sa scale ng vendor kapag nilagay ang 1kg test weight"
                )
                self.assertEqual(structured_state("WeightMeasures", incident)[0], expected)
        incident, = self.pipeline.extract(
            "The scale read 900g with a 1kg test weight, but the reference scale was faulty"
        )
        self.assertEqual(structured_state("WeightMeasures", incident)[0], "insufficient")

    def test_structured_equipment_binds_the_observed_failure_to_its_own_requirement(self):
        for description, expected in [
            ("Walang fire extinguisher, required to", "supported"),
            ("No fire extinguisher in the stall, apron required", None),
            ("No fire extinguisher in the stall, hindi required", None),
            ("No fire extinguisher was missing, the contract requires an extinguisher", "insufficient"),
        ]:
            with self.subTest(description=description):
                incident, = self.pipeline.extract(description)
                decision = structured_state("Stall Management", incident)
                self.assertEqual(decision[0] if decision else None, expected)

    def test_date_evidence_identifies_which_object_expired(self):
        incident, = self.pipeline.extract(
            "Food was for sale and the vendor was operating with a permit that expired on 2025-03-04, "
            "inspection date 2025-03-05"
        )
        self.assertIsNone(structured_state("Sanitation", incident))
        self.assertEqual(structured_state("Permit & Licensing", incident)[0], "supported")

    def test_explicit_expiry_requires_the_affected_stock_to_remain_on_sale(self):
        incident, = self.pipeline.extract("yung panindang de-lata expired na, binibenta parin")
        self.assertEqual(structured_state("Sanitation", incident)[0], "supported")
        incident, = self.pipeline.extract("The canned goods expired but were removed from sale")
        self.assertIsNone(structured_state("Sanitation", incident))
        incident, = self.pipeline.extract("No canned goods were expired among those for sale")
        self.assertIsNone(structured_state("Sanitation", incident))

    def test_all_categories_have_three_states_in_each_contrastive_partition(self):
        path = Path(__file__).resolve().parents[1] / "data/incident_contrasts.tsv"
        splits = contrastive_examples(path, list(self.pipeline.taxonomy))
        for rows in splits.values():
            self.assertEqual(len(rows), 29 * 3)

    def test_transfer_needs_verified_authorization_status(self):
        for description, expected in [
            ("Subleasing si vendor", None),
            ("The vendor was subletting and the lessor confirmed written consent", "compliant"),
            ("The vendor subleased the stall and the lessor confirmed no written consent", "supported"),
        ]:
            with self.subTest(description=description):
                incident, = self.pipeline.extract(description)
                decision = structured_state("Stall Rental", incident)
                self.assertEqual(decision[0] if decision else None, expected)


if __name__ == "__main__":
    unittest.main()
