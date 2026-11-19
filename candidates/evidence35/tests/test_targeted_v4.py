import unittest

from src.engine import normalize
from src.targeted_v4 import with_targeted_v4


class TargetedV4Tests(unittest.TestCase):
    def test_adds_independent_findings_from_the_same_note(self):
        note = ("Vendor ID posted at Stall D-4, but it was assigned to Stall D-8. "
                "Truck idled at Bay 2. No idling at Bay 2.")
        original = {"Sanitation"}
        findings, checks = with_targeted_v4(note, original, normalize)
        self.assertEqual(findings, {"Sanitation", "Vendor Identification", "Traffic"})
        self.assertEqual(original, {"Sanitation"})
        self.assertEqual(checks["vendor-id-stall"][1], ["Vendor Identification"])
        self.assertEqual(checks["traffic-loading"][1], ["Traffic"])

    def test_deduplicates_two_checks_for_the_same_category(self):
        note = ("Opening log: stall opened 2 days last week. Stall must open at least 4 days per week. "
                "Market office closed Stall A-4 for repairs, no entry. Vendor entered Stall A-4.")
        findings, checks = with_targeted_v4(note, set(), normalize)
        self.assertEqual(findings, {"Stall Occupancy"})
        self.assertEqual(checks["stall-operating-days"][1], ["Stall Occupancy"])
        self.assertEqual(checks["stall-repair-closure"][1], ["Stall Occupancy"])

    def test_event_approval_veto_preserves_other_baseline_findings(self):
        note = "The vendor hosted a magic show. The event permit was for that magic show."
        baseline = {"Entertainment Activities", "Vendor Identification"}
        findings, checks = with_targeted_v4(note, baseline, normalize)
        self.assertEqual(findings, {"Vendor Identification"})
        self.assertEqual(checks["event-approval"][2], ["Entertainment Activities"])


if __name__ == "__main__":
    unittest.main()
