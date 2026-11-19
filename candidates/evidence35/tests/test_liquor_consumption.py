import unittest

from src.engine import normalize
from src.liquor_consumption import consumption_evidence, consumption_safeguard, load_consumption_policy


class LiquorConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_consumption_policy()

    def triggers(self, text, policy=None):
        return {rule for rule, _ in consumption_evidence(text, normalize, policy or self.policy)}

    def test_consumption_in_a_public_place_needs_no_vendor_role(self):
        self.assertEqual(self.triggers("Uminom ng alak ang bisita sa pampublikong lugar."), {"public_place"})

    def test_selling_is_an_independent_policy_condition(self):
        note = "Si tindera nagbebenta habang umiinom ng beer."
        self.assertEqual(self.triggers(note), {"actively_selling"})
        public_only = {**self.policy, "qualifying_contexts": ["public_place"]}
        self.assertEqual(self.triggers(note, public_only), set())

    def test_consumption_and_selling_must_describe_the_same_person(self):
        note = "Habang nagtitinda ang vendor, umiinom ng alak ang katulong."
        self.assertEqual(self.triggers(note), set())

    def test_negated_non_alcoholic_and_unconfirmed_consumption_do_not_trigger(self):
        for note in (
            "Walang umiinom ng beer sa loob ng palengke.",
            "The seller was drinking non-alcoholic beer while selling.",
            "The visitor was drinking gin in the public park. This was not verified.",
            "The visitor carried an opened bottle of gin through the public park.",
        ):
            with self.subTest(note=note):
                self.assertEqual(self.triggers(note), set())

    def test_safeguard_vetoes_negated_or_unscoped_inherited_consumption(self):
        for note, expected in (
            ("Walang umiinom ng alak.", "negated_consumption"),
            ("No one was drinking. Sealed liquor bottles were on display.", "negated_consumption"),
            ("The stallholder drank rum.", "insufficient_consumption_evidence"),
            ("The stallholder drank rum in a public park.", None),
        ):
            with self.subTest(note=note):
                self.assertEqual(consumption_safeguard(note, normalize, self.triggers(note)), expected)

    def test_consumption_veto_leaves_independent_liquor_evidence_intact(self):
        note = "No one was drinking. A separate liquor sale violated an active ban."
        self.assertIsNone(consumption_safeguard(note, normalize, (), independent_liquor_evidence=True))


if __name__ == "__main__":
    unittest.main()
