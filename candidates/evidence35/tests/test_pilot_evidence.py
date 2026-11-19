import unittest

from src.engine import normalize
from src.incidents import incident_spans
from src.liquor_evidence import (
    LiquorPolicy, load_pilot_policy, market_drinking_comparisons, policy_comparisons, sale_limits,
)
from src.pilot_evidence import shared_evidence, targeted_evidence


def units(text):
    return incident_spans(text, normalize)


class PilotEvidenceTests(unittest.TestCase):
    def test_shared_verification_requires_category_and_structured_breach(self):
        bad, = units("900g ang lumalabas sa scale ng vendor kapag nilagay ang 1kg test weight")
        good, = units("1000g ang lumalabas sa scale ng vendor kapag nilagay ang 1kg test weight")
        self.assertEqual(list(shared_evidence(bad, ["WeightMeasures"])),
                         [("WeightMeasures", "scale_test_comparison")])
        self.assertEqual(list(shared_evidence(bad, ["Sanitation"])), [])
        self.assertEqual(list(shared_evidence(good, ["WeightMeasures"])), [])

    def test_obstruction_requires_vendor_placement_and_observed_passage_impact(self):
        observed, = units("Nagtali ang tindero ng tarp sa pasilyo kaya hindi makadaan ang mamimili")
        clear, = units("The vendor hung a banner beside the aisle and customers could pass")
        self.assertEqual(list(targeted_evidence(observed)), [("Obstruction", "observed_passage_impact")])
        self.assertEqual(list(targeted_evidence(clear)), [])

    def test_inspection_interference_preserves_followup_uncertainty(self):
        observed = "Hinablot ng tindero ang medida ng inspektor at itinapon ito"
        definite, = units(observed)
        self.assertEqual(list(targeted_evidence(definite)),
                         [("Resisting Authority", "observed_inspection_interference")])
        self.assertFalse(any(list(targeted_evidence(unit)) for unit in units(observed + ". This was not confirmed.")))

    def test_liquor_age_comparison_requires_the_buyers_verified_age(self):
        rule = ". The rule states liquor may not be sold to anyone under 21."
        cases = [
            ("The seller sold wine to a buyer whose ID shows age 20", "supported"),
            ("The seller sold wine to a buyer whose ID shows age 21", "compliant"),
            ("The seller sold wine to a buyer who said she was 20 years old", "insufficient"),
            ("The seller sold wine to a buyer and the vendor's ID shows age 20", "insufficient"),
            ("Nagbenta ang tindera ng beer sa buyer na 22 years old ayon sa ID niya", "compliant"),
            ("The seller sold wine to a buyer whose school ID shows age 20. This was not confirmed", None),
        ]
        for description, state in cases:
            with self.subTest(description=description):
                result = [state for unit in units(description + rule) for state, _ in sale_limits(unit)]
                self.assertEqual(result, [] if state is None else [state])

    def test_liquor_window_uses_sale_time_and_supports_overnight_windows(self):
        rule = ". Licensed stalls may sell liquor only from 7:00 PM to 1:00 AM."
        cases = [
            ("The seller sold wine at 1:05 AM", "supported"),
            ("The seller sold wine at 12:30 AM", "compliant"),
            ("The seller sold wine at 7:00 PM", "compliant"),
            ("The stall opened at 6:30 PM and the seller sold wine", "insufficient"),
            ("The seller sold alcohol free beer at 6:30 PM", None),
            ("The seller did not sell beer at 6:30 PM", None),
        ]
        for description, state in cases:
            with self.subTest(description=description):
                result = [state for unit in units(description + rule) for state, _ in sale_limits(unit)]
                self.assertEqual(result, [] if state is None else [state])

    def test_pilot_policy_supplies_threshold_for_id_verified_age(self):
        note = (
            "The vendor sold wine to a 17-year-old customer. "
            "The buyer's age was verified from an identification card."
        )
        policy = load_pilot_policy()
        self.assertIn(("supported", "verified_buyer_age"), list(policy_comparisons(note, normalize, policy)))
        lower_age = LiquorPolicy("different synthetic policy", 17, policy.latest_sale_time)
        self.assertIn(("compliant", "verified_buyer_age"), list(policy_comparisons(note, normalize, lower_age)))

    def test_pilot_cutoff_uses_observed_sale_time_and_allows_equality(self):
        policy = load_pilot_policy()
        for clock, expected in [("7:59 PM", "compliant"), ("8:00 PM", "compliant"), ("8:01 PM", "supported")]:
            with self.subTest(clock=clock):
                note = f"At {clock}, the inspector observed the vendor completing a liquor sale."
                checks = list(policy_comparisons(note, normalize, policy))
                self.assertIn((expected, "documented_liquor_sale_cutoff"), checks)

    def test_pilot_policy_keeps_unverified_or_unrelated_facts_insufficient(self):
        policy = load_pilot_policy()
        cases = [
            "The seller sold wine to a buyer who said he was 16. The buyer's age was not verified.",
            "The vendor's ID shows age 16. The vendor sold wine to a customer.",
            "The stall opened at 8:30 PM and the seller sold wine.",
            "The seller sold wine at 9:00 PM. The transaction time was unverified.",
            "A customer stated that he purchased liquor from the vendor at 9:00 PM.",
        ]
        for note in cases:
            with self.subTest(note=note):
                self.assertFalse(any(state == "supported" for state, _ in policy_comparisons(note, normalize, policy)))

    def test_market_drinking_requires_inside_location_for_any_person(self):
        cases = [
            ("umiinom ng alak sa pampublikong lugar", "insufficient"),
            ("si vendor nagtitinda habang umiinom ng alak", "insufficient"),
            ("umiinom ng alak sa loob ng palengke", "supported"),
            ("A shopper was drinking beer inside the public market", "supported"),
            ("A shopper drank beer outside the market", "compliant"),
            ("A shopper was drinking beer in the market parking lot", "insufficient"),
            ("Umiinom daw ng alak sa loob ng palengke", "insufficient"),
            ("Drinking beer inside the market is prohibited", "insufficient"),
            ("A shopper drank beer outside, then walked inside the market", "insufficient"),
        ]
        for note, expected in cases:
            with self.subTest(note=note):
                self.assertEqual(list(market_drinking_comparisons(note, normalize)),
                                 [(expected, "observed_drinking_inside_market")])
        self.assertEqual(list(market_drinking_comparisons("Hindi naman umiinom ng alak sa loob ng palengke", normalize)),
                         [])


if __name__ == "__main__":
    unittest.main()
