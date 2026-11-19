import json
from pathlib import Path
import unittest

from src.engine import normalize
from src.traffic_loading import CATEGORY, assess_traffic_loading, with_traffic_loading


CASES = Path(__file__).resolve().parents[1] / "evaluation/traffic-loading/fresh-cases.json"


class TrafficLoadingTests(unittest.TestCase):
    def test_matched_examples_in_three_languages(self):
        for row in json.loads(CASES.read_text(encoding="utf-8")):
            with self.subTest(group=row["group"], state=row["state"]):
                self.assertLessEqual(len(row["description"]), 120)
                check = assess_traffic_loading(row["description"], normalize)
                self.assertIsNotNone(check)
                self.assertEqual(check.state, row["state"])

    def test_location_must_belong_to_the_observed_vehicle(self):
        for note in (
            "Truck waited with its engine running. Vehicles waiting at the loading bay must switch off their engines.",
            "Vendor sold fish at the loading bay. The truck waited with its engine running. No idling at the loading bay.",
            "Truck idled at Bay 3. No idling at Bay 2.",
            "Truck idled in the parking lot. No idling at the loading bay, engines permitted in the parking lot.",
        ):
            with self.subTest(note=note):
                findings, check = with_traffic_loading(note, {"Sanitation"}, normalize)
                self.assertEqual(findings, {"Sanitation"})
                self.assertEqual(check.state, "insufficient")

    def test_rules_and_engine_status_must_be_verified(self):
        for note in (
            "Truck idled at Bay 2. No idling at Bay 2, except vehicles with clearance.",
            "Truck idled at Bay 2. No idling at Bay 2. The sign was unreadable.",
            "Truck was not idling while waiting in Bay 2. No idling in Bay 2.",
            "Truck waited at Bay 2, engine was running then switched off. Engines must be off in Bay 2.",
            "Truck waited at Bay 2 with written clearance to keep its engine on. Engine status unknown.",
            "Truck idled at Bay 2. No idling at Bay 2, but the rule is not in effect.",
        ):
            with self.subTest(note=note):
                self.assertNotIn(CATEGORY, with_traffic_loading(note, set(), normalize)[0])

    def test_loading_requires_an_observed_operation_and_matching_prohibition(self):
        for note in (
            "Truck waited to unload at the curb. Deliveries must be unloaded at the designated loading bay.",
            "Truck loaded boxes at the curb. No unloading at the curb.",
            "Truck unloaded boxes at the curb. Trucks must switch off their engines while unloading in the loading bay.",
            "Truck unloaded boxes at the curb. No unloading at the curb, except with written clearance.",
        ):
            with self.subTest(note=note):
                self.assertNotIn(CATEGORY, with_traffic_loading(note, set(), normalize)[0])

    def test_idling_is_observed_even_if_loading_has_not_started(self):
        note = "Truck idled at Bay 2 while waiting to unload. No idling at Bay 2."
        self.assertEqual(assess_traffic_loading(note, normalize).state, "supported")

    def test_keeps_every_existing_finding(self):
        note = "Truck waited at Bay 2 with engine off. Engines must be off at Bay 2."
        findings, check = with_traffic_loading(note, {CATEGORY, "Obstruction"}, normalize)
        self.assertEqual(findings, {CATEGORY, "Obstruction"})
        self.assertEqual(check.state, "compliant")


if __name__ == "__main__":
    unittest.main()
