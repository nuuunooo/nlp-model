import json
from pathlib import Path
import unittest

from src.engine import normalize
from src.vendor_id_display import CATEGORY, assess_vendor_id_display, with_vendor_id_display


CASES = Path(__file__).resolve().parents[1] / "evaluation/vendor-id-display/fresh-cases.json"


class VendorIDDisplayTests(unittest.TestCase):
    def test_fresh_matched_groups(self):
        for row in json.loads(CASES.read_text(encoding="utf-8")):
            with self.subTest(group=row["group"], state=row["state"]):
                self.assertLessEqual(len(row["description"]), 120)
                result = assess_vendor_id_display(row["description"], normalize)
                self.assertIsNotNone(result)
                self.assertEqual(result.state, row["state"])

    def test_observed_placement_can_follow_the_requirement(self):
        note = "ID must be displayed at eye level. Seller trading, ID hung above eye level."
        self.assertEqual(assess_vendor_id_display(note, normalize).state, "supported")

    def test_scope_guards_require_a_verified_breach(self):
        for note in (
            "Seller trading, ID hung above eye level. ID must be posted.",
            "Seller trading, ID hung above eye level daw. ID must be posted at eye level.",
            "Seller trading, ID hung above eye level. It was moved to eye level. ID must be posted at eye level.",
            "Seller trading at Stall B-1, her ID left on the cart beside Stall B-1. ID must be posted where currently trading.",
            "Seller trading at Stall B-1, her ID left on the cart in parking. The display duty was not verified.",
            "Seller trading, ID posted at eye level and a box covered the menu. ID must be posted with the photo legible.",
            "Seller trading, ID posted at eye level while the sign hung above eye level. ID must be posted at eye level.",
            "Vendor standing by the closed stall, vendor ID hung above eye level. ID must be posted at eye level.",
            "Porter ID hung above eye level while the vendor was selling. ID must be posted at eye level.",
        ):
            with self.subTest(note=note):
                findings, _ = with_vendor_id_display(note, {"Sanitation"}, normalize)
                self.assertEqual(findings, {"Sanitation"})

    def test_preserves_original_findings_even_when_display_check_is_compliant(self):
        note = "Seller selling, ID posted at the stall front at eye level, name and photo legible."
        findings, check = with_vendor_id_display(note, {CATEGORY, "Traffic"}, normalize)
        self.assertEqual(findings, {CATEGORY, "Traffic"})
        self.assertEqual(check.state, "compliant")

    def test_unrelated_uncertainty_does_not_block_the_id_check(self):
        note = "Seller trading, ID hung above eye level. ID must be posted at eye level. Di na-check kung barado ang kanal."
        findings, check = with_vendor_id_display(note, {"Sanitation"}, normalize)
        self.assertEqual(findings, {CATEGORY, "Sanitation"})
        self.assertEqual(check.state, "supported")


if __name__ == "__main__":
    unittest.main()
