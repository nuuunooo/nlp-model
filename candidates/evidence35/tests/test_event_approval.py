import json
from pathlib import Path
import unittest

from src.engine import normalize
from src.event_approval import CATEGORY, assess_event_approval, with_event_approval


CASES = Path(__file__).resolve().parents[1] / "evaluation/event-approval/fresh-cases.json"


class EventApprovalTests(unittest.TestCase):
    def test_fresh_matched_groups(self):
        for row in json.loads(CASES.read_text(encoding="utf-8")):
            with self.subTest(group=row["group"], state=row["state"]):
                self.assertLessEqual(len(row["description"]), 120)
                result = assess_event_approval(row["description"], normalize)
                self.assertIsNotNone(result)
                self.assertEqual(result.state, row["state"])

    def test_addon_only_changes_the_approval_finding(self):
        supported = "Vendor held a concert. Permit was for a raffle only."
        compliant = "Vendor held a concert. Permit was for this concert."
        self.assertEqual(with_event_approval(supported, {"Sanitation"}, normalize)[0], {CATEGORY, "Sanitation"})
        self.assertEqual(with_event_approval(compliant, {CATEGORY, "Traffic"}, normalize)[0], {"Traffic"})
        self.assertEqual(with_event_approval(compliant, {"Traffic"}, normalize)[0], {"Traffic"})
        unrelated = compliant + " Speakers exceeded the sound limit."
        self.assertEqual(with_event_approval(unrelated, {CATEGORY, "Traffic"}, normalize)[0], {CATEGORY, "Traffic"})

    def test_explicitly_unverified_approval_can_veto_only_an_approval_only_note(self):
        uncertain = "Vendor held a concert. The event permit scope was unreadable."
        self.assertEqual(with_event_approval(uncertain, {CATEGORY}, normalize)[0], set())
        separate_check = "Vendor held a concert. The event permit scope was unreadable. Crowd exceeded the cap."
        self.assertEqual(with_event_approval(separate_check, {CATEGORY}, normalize)[0], {CATEGORY})

    def test_explicit_difference_and_calendar_boundary(self):
        for note in (
            "Vendor hosted an event. Permit was for a different event.",
            "Vendor staged a concert on 2026-12-30. Permit valid from 2026-12-31 to 2027-01-02.",
        ):
            with self.subTest(note=note):
                self.assertEqual(assess_event_approval(note, normalize).state, "supported")
        result = assess_event_approval(
            "Vendor staged a concert on 2027-01-02. Permit valid from 2026-12-31 to 2027-01-02.", normalize,
        )
        self.assertEqual(result.state, "compliant")
        self.assertEqual(assess_event_approval(
            "Vendor held a concert on Nov 3. Permit valid from Nov 1-Nov 4.", normalize,
        ).state, "compliant")

    def test_scope_ambiguities_and_uncertain_facts_do_not_add_findings(self):
        for note in (
            "Vendor held the concert permit for a raffle.",
            "Vendor did not hold a concert. Permit was for a raffle.",
            "Hindi nagdaos ng konsiyerto ang tindero. Pahintulot para sa bunutan.",
            "Vendor held a concert. Permit was for a raffle. Permit scope was not verified.",
            "Stall A-1 held a concert. Stall B-2 permit for a raffle only.",
            "Vendor held a concert. Permit covers bingo and more.",
            "Vendor held a concert. Permit covers bingo unless another event is authorized.",
            "Vendor held a concert on the 16th. Permit for the 14th and Sundays.",
            "Vendor held a concert on Saturday. Active standing permit covers concerts every second Saturday.",
            "Vendor held a concert on Aug 31. Permit was for Aug 32.",
            "Vendor held a concert. Permit for a concert through next week.",
            "Vendor reused last month's event approval for a new concert.",
        ):
            with self.subTest(note=note):
                findings, check = with_event_approval(note, {"Sanitation"}, normalize)
                self.assertEqual(findings, {"Sanitation"})
                self.assertEqual(check.state, "insufficient")

    def test_permit_scope_does_not_leak_across_events(self):
        note = "Stall A-1 held a concert. Stall B-2 held a raffle. Stall B-2 permit covers raffle only."
        self.assertEqual(assess_event_approval(note, normalize).state, "insufficient")

    def test_unrelated_uncertainty_does_not_veto_a_supported_event(self):
        note = "Vendor held a concert. Permit was for a raffle only. Di pa na-check kung barado ang kanal."
        self.assertEqual(assess_event_approval(note, normalize).state, "supported")


if __name__ == "__main__":
    unittest.main()
