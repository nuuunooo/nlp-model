import json
from pathlib import Path
import unittest

from src.engine import normalize
from src.stall_repair_closure import CATEGORY, assess_repair_closure, with_repair_closure


CASES = Path(__file__).resolve().parents[1] / "evaluation/stall-repair-closure/fresh-cases.json"


class StallRepairClosureTests(unittest.TestCase):
    def test_matched_examples_in_three_languages(self):
        for row in json.loads(CASES.read_text(encoding="utf-8")):
            with self.subTest(group=row["group"], state=row["state"]):
                self.assertLessEqual(len(row["description"]), 120)
                check = assess_repair_closure(row["description"], normalize)
                self.assertIsNotNone(check)
                self.assertEqual(check.state, row["state"])

    def test_tape_or_a_directive_does_not_establish_a_breach(self):
        for note in (
            "Vendor sold behind safety tape. No occupancy in a row closed for repairs until it reopens.",
            "Repair notice: Stall A-1 closed for repairs, no selling. Vendor was told no selling in Stall A-1.",
            "Repair notice: Stall A-1 closed for repairs. No selling restriction was issued. Vendor sold in Stall A-1.",
            "Repair notice: Stall A-1 closed for repairs, no entry. Vendor entered Stall A-2.",
            "Repair notice: closed stall for repairs, no entry. Vendor entered inside. The closure was lifted.",
            "Repair notice: closed stall for repairs, no entry. Vendor entered inside. Permission not verified.",
            "Vendor entered a closed stall. It was the seller's own voluntary closing day.",
            "Vendor sold outside the closed stall. No occupancy in stalls closed for repairs.",
        ):
            with self.subTest(note=note):
                findings, _ = with_repair_closure(note, {"Sanitation"}, normalize)
                self.assertEqual(findings, {"Sanitation"})

    def test_clearance_exception_needs_a_verified_status(self):
        scope = "Repair notice: Stall A-1 closed for repairs, no entry except with written clearance."
        entered = " Vendor entered Stall A-1"
        self.assertEqual(assess_repair_closure(scope + entered + ".", normalize).state, "insufficient")
        self.assertEqual(assess_repair_closure(
            scope + entered + " with written clearance.", normalize,
        ).state, "compliant")
        self.assertEqual(assess_repair_closure(
            scope + entered + " without clearance.", normalize,
        ).state, "supported")

    def test_permission_to_collect_stock_does_not_allow_trading(self):
        note = (
            "Repair notice: Stall A-1 closed for repairs, no selling. "
            "Vendor sold in Stall A-1 with written clearance to retrieve stock only."
        )
        check = assess_repair_closure(note, normalize)
        self.assertEqual(check.state, "supported")
        self.assertEqual(check.reason, "prohibited_use_outside_granted_access")

    def test_dates_are_bound_to_the_stall_and_notice(self):
        scope = "Repair notice: Stall F-8 closed from Nov 3 through Nov 5, no entry."
        self.assertEqual(assess_repair_closure(
            scope + " Vendor entered Stall F-8 Nov 4.", normalize,
        ).state, "supported")
        self.assertEqual(assess_repair_closure(
            scope + " Vendor entered Stall F-8 Nov 6.", normalize,
        ).state, "compliant")
        self.assertEqual(assess_repair_closure(
            scope + " Vendor entered Stall F-8.", normalize,
        ).state, "insufficient")
        until = "Repair notice: Stall F-8 closed from Nov 3 until Nov 5, no entry."
        self.assertEqual(assess_repair_closure(
            until + " Vendor entered Stall F-8 Nov 5.", normalize,
        ).state, "insufficient")

    def test_preserves_baseline_predictions_on_permitted_access(self):
        note = "Repair notice: Stall A-1 closed for repairs. Vendor entered Stall A-1 with written clearance."
        findings, check = with_repair_closure(note, {CATEGORY, "Traffic"}, normalize)
        self.assertEqual(findings, {CATEGORY, "Traffic"})
        self.assertEqual(check.state, "compliant")


if __name__ == "__main__":
    unittest.main()
