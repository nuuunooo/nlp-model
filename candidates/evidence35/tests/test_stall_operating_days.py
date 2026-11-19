import json
from pathlib import Path
import unittest

from src.engine import normalize
from src.stall_operating_days import CATEGORY, assess_operating_days, with_operating_days


CASES = Path(__file__).resolve().parents[1] / "evaluation/stall-operating-days/fresh-cases.json"


class StallOperatingDaysTests(unittest.TestCase):
    def test_fresh_matched_groups(self):
        for row in json.loads(CASES.read_text(encoding="utf-8")):
            with self.subTest(group=row["group"], state=row["state"]):
                self.assertLessEqual(len(row["description"]), 120)
                check = assess_operating_days(row["description"], normalize)
                self.assertIsNotNone(check)
                self.assertEqual(check.state, row["state"])

    def test_records_have_to_match_the_duty_and_period(self):
        for note in (
            "Opening log: Stall A-1 opened 2 days last week. Stall B-1 must open at least 4 days per week.",
            "Opening log: stall opened 14 days last month. Stall must open at least 4 days per week.",
            "Opening log: stall open 2 days so far this week. Stall must open at least 4 days per week.",
            "Opening log: stall scheduled to open 2 days last week. Stall must open at least 4 days per week.",
            "Opening log: stall closed for 2 days last week. Stall must open at least 4 days per week.",
            "Attendance log: awardee absent 3 days last week. Awardee must operate at least 4 days per week.",
            "Attendance log: awardee present 4 days last week. Awardee must personally operate at least 4 days per week.",
            "Attendance log: awardee worked 2 days last week. Stall must open at least 4 days per week.",
            "Opening log has missing pages. Opening log: stall opened 2 days last week. Stall must open at least 4 days per week.",
            "Opening log: stall opened 2 days last week. Stall must open at least 4 days per week. Log entries were missing.",
            "Attendance log: awardee worked 2 days last week on approved leave. Awardee must work at least 4 days per week.",
        ):
            with self.subTest(note=note):
                findings, check = with_operating_days(note, {"Sanitation"}, normalize)
                self.assertEqual(findings, {"Sanitation"})
                self.assertEqual(check.state, "insufficient")

    def test_preserves_v4_findings_on_a_compliant_record(self):
        note = "Opening log: stall opened 4 days last week. Stall must open at least 4 days/week."
        findings, check = with_operating_days(note, {CATEGORY, "Traffic"}, normalize)
        self.assertEqual(findings, {CATEGORY, "Traffic"})
        self.assertEqual(check.state, "compliant")
        self.assertEqual((check.recorded_days, check.minimum_days, check.period), (4, 4, "week"))

    def test_helpers_do_not_count_toward_personal_operation(self):
        note = ("Attendance log: awardee did not work at all for five weeks while helpers ran the stall. "
                "Awardee must personally operate at least 4 days weekly.")
        check = assess_operating_days(note, normalize)
        self.assertEqual((check.state, check.recorded_days, check.minimum_days), ("supported", 0, 4))

    def test_repeated_weekly_record_and_local_uncertainty(self):
        note = ("Section log: awardee worked only on Sundays for the past month. "
                "Awardee must personally operate at least 4 days a week. Di na-check kung barado ang kanal.")
        findings, check = with_operating_days(note, {"Traffic"}, normalize)
        self.assertEqual(findings, {CATEGORY, "Traffic"})
        self.assertEqual((check.state, check.recorded_days, check.minimum_days), ("supported", 1, 4))


if __name__ == "__main__":
    unittest.main()
