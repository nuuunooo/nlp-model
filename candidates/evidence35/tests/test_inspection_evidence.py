import unittest

from src.engine import normalize
from src.inspection_evidence import assess_market_note
from src.liquor_consumption import load_consumption_policy


class MarketInspectionEvidenceTests(unittest.TestCase):
    def assess(self, note, *, market=True):
        return assess_market_note(note, normalize, load_consumption_policy(), market_inspection=market)

    def test_missing_hairnet_requires_observed_food_work(self):
        findings, _, _ = self.assess("The helper was serving ready to eat food without a hairnet.")
        self.assertEqual(set(findings), {"DressCode"})
        findings, _, _ = self.assess("There is no hairnet in the unopened supply box.")
        self.assertEqual(findings, {})

    def test_absent_id_differs_from_id_that_could_not_be_shown(self):
        findings, _, _ = self.assess("Walang market ID ang nagbebenta ng gulay.")
        self.assertIn("Vendor Identification", findings)
        findings, review, _ = self.assess("Walang suot na ID si kuya, nasa bulsa daw pero di niya mapakita.")
        self.assertNotIn("Vendor Identification", findings)
        self.assertIn("Vendor Identification", review)

    def test_entrance_needs_market_context_and_double_rate_needs_verification(self):
        note = "Ang mga kargador sa may entrance ay nag-iinuman ng gin at ayaw tumanggap ng customer na di magbabayad ng doble."
        findings, review, _ = self.assess(note)
        self.assertEqual(set(findings), {"Liquor"})
        self.assertIn("Porter Regulation", review)
        findings, _, _ = self.assess(note, market=False)
        self.assertNotIn("Liquor", findings)

    def test_permit_hours_compare_midnight_and_leave_timely_or_planned_events_unflagged(self):
        for time, flags in (("12mn", True), ("10pm", False), ("9:30pm", False)):
            with self.subTest(time=time):
                note = f"Tuloy ang videoke hanggang {time} kahit 10pm lang ang allowed sa entertainment permit."
                findings, _, _ = self.assess(note)
                self.assertEqual("Entertainment Activities" in findings, flags)
        findings, _, _ = self.assess("Tuloy ang videoke bukas hanggang 12mn kahit 10pm lang ang allowed sa entertainment permit.")
        self.assertNotIn("Entertainment Activities", findings)

    def test_warning_and_unrepaired_chiller_indicate_management_without_a_food_safety_finding(self):
        findings, _, _ = self.assess("Sira ang chiller at di pa rin pinapagawa kahit may warning na.")
        self.assertEqual(set(findings), {"Stall Management"})
        findings, _, _ = self.assess("Sira dati ang chiller pero naayos na pagkatapos ng warning.")
        self.assertEqual(findings, {})

    def test_sanitation_compliance_is_limited_to_documented_conditions(self):
        findings, _, compliant = self.assess("Malinis ang stall, may yelo ang isda, walang langaw.")
        self.assertEqual(findings, {})
        self.assertEqual(compliant, ["Sanitation"])


if __name__ == "__main__":
    unittest.main()
