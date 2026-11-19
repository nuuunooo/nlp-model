import json
from pathlib import Path
import unittest

from src.engine import normalize
from src.vendor_id_stall import CATEGORY, assess_vendor_id_stall, with_vendor_id_stall


CASES = Path(__file__).resolve().parents[1] / "evaluation/vendor-id-stall/fresh-cases.json"


class VendorIDStallTests(unittest.TestCase):
    def test_fresh_matched_groups(self):
        for row in json.loads(CASES.read_text(encoding="utf-8")):
            with self.subTest(group=row["group"], state=row["state"]):
                self.assertLessEqual(len(row["description"]), 120)
                check = assess_vendor_id_stall(row["description"], normalize)
                self.assertIsNotNone(check)
                self.assertEqual(check.state, row["state"])

    def test_preserves_every_v4_finding(self):
        baseline = {"Sanitation", "Traffic"}
        wrong = "Vendor ID posted at Stall A-1, but it was assigned to Stall A-2."
        matched = "Vendor ID posted at Stall A-1, and it was assigned to Stall A-1."
        self.assertEqual(with_vendor_id_stall(wrong, baseline, normalize)[0], baseline | {CATEGORY})
        self.assertEqual(with_vendor_id_stall(matched, baseline | {CATEGORY}, normalize)[0], baseline | {CATEGORY})
        self.assertEqual(with_vendor_id_stall(matched, baseline, normalize)[0], baseline)

    def test_compares_normalized_identifiers(self):
        note = "Vendor ID posted at Stall A-12, and it was assigned to Stall A12."
        self.assertEqual(assess_vendor_id_stall(note, normalize).state, "compliant")

    def test_explicit_relative_assignment_needs_no_stall_number(self):
        for note in (
            "Vendor ID is posted here, but it belongs to a different store.",
            "Naka-display yung vendor ID pero para sa ibang stall ang card.",
        ):
            with self.subTest(note=note):
                self.assertEqual(assess_vendor_id_stall(note, normalize).state, "supported")

    def test_card_assignment_and_display_can_be_stated_in_either_order(self):
        for note in (
            "Vendor ID for Stall A-2 was displayed at Stall A-1.",
            "Vendor ID posted at Stall A-1 but assigned to Stall A-2.",
        ):
            with self.subTest(note=note):
                self.assertEqual(assess_vendor_id_stall(note, normalize).state, "supported")

    def test_incomplete_or_unrelated_facts_do_not_add_findings(self):
        for note in (
            "Vendor ID posted at Stall A-1. Unclear if it was assigned to Stall A-2.",
            "Vendor ID posted at Stall A-1, but it was assigned to Stall A-2. This was not verified.",
            "Vendor ID posted at Stall A-1, but its permit was assigned to Stall A-2.",
            "Vendor ID posted at Stall A-1, but it was assigned to Stall A-2 and Stall A-1.",
            "Seller trading at Stall A-1. Another vendor ID is displayed at Stall A-2.",
            "Seller trading at Stall A-1, her ID posted at Stall A-2.",
            "Naiwan ang vendor ID sa puwesto A-1, para sa puwesto A-2.",
            "Vendor ID issued to Stall A-2 is in a drawer at Stall A-1.",
            "Seller trading at Stall A-1, ID left on the cart in the parking area.",
            "Porter ID posted at Stall A-1, but it was assigned to Stall A-2.",
            "Vendor ID posted here, but the business permit belongs to a different store.",
        ):
            with self.subTest(note=note):
                findings, check = with_vendor_id_stall(note, {"Sanitation"}, normalize)
                self.assertEqual(findings, {"Sanitation"})
                if check:
                    self.assertEqual(check.state, "insufficient")

    def test_independent_finding_survives_unrelated_uncertainty(self):
        note = "Vendor ID posted at Stall A-1, but it was assigned to Stall A-2. Di na-check kung barado ang kanal."
        self.assertEqual(assess_vendor_id_stall(note, normalize).state, "supported")


if __name__ == "__main__":
    unittest.main()
