"""Behavioral checks for certainty, scope, exceptions and numeric boundaries."""
import unittest

from src.engine import analyze_ticket, catalog, normalize
from src.incidents import incident_spans


class BreachEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy, cls.lexicon = catalog()

    def codes(self, text, model=True, llm=False):
        taxonomy = self.taxonomy
        class Overconfident:
            uses_category_thresholds = True
            def predict(self, value):
                return [{"code":code,"confidence":.999} for code in taxonomy]
        class UnreliableLLM:
            def classify(self, value, _taxonomy):
                return [{"code":code,"evidence":value} for code in taxonomy]
        _, findings = analyze_ticket({"ticket_id":"fixture","description":text},
            self.taxonomy, self.lexicon, Overconfident() if model else None,
            UnreliableLLM() if llm else None)
        return {finding["code"] for finding in findings}

    def test_compliance_survives_every_category_being_nominated(self):
        for text in (
            'Business permit current and posted. Occupant matches the award.',
            'Daily fee paid, receipt shown. Rent paid up to date per ledger.',
            'Garbage in sealed bags. Knives in a locked steel box.',
            'Smell of alcohol, no one seen drinking or selling.',
            'Light flickering, maintenance duty unknown.',
            'May tsismis na walang permit, hindi na-verify.',
            'If a vendor has no vendor ID, an action would be appropriate.',
            'Rule: vendors must not block the exit with crates.',
            'A utensil seller displays knives as merchandise.',
        ):
            with self.subTest(text=text):
                self.assertEqual(self.codes(text), set())
                self.assertEqual(self.codes(text,model=False,llm=True),set())

    def test_independent_incident_and_followup_qualification(self):
        text = ('Fish sold as 1 kg measured at 850 g. '
                'Vendor had no vendor ID. This was not confirmed.')
        self.assertEqual(self.codes(text), {'WeightMeasures'})
        text = ('The stall is occupied by the awardee; '
                'stacked crates fully block the fire exit; '
                'may tsismis na walang permit, hindi na-verify.')
        self.assertEqual(self.codes(text), {'Obstruction'})

    def test_weight_reliability_qualifier_does_not_erase_other_incident(self):
        text = ('Vendor had no vendor ID. Fish weighed 900 g against 1 kg; '
                'drained weight not taken.')
        self.assertEqual(self.codes(text), {'Vendor Identification'})

    def test_role_specific_approval_and_registration(self):
        for text, code in (
            ('Vendor built a new concrete counter without a permit from the Market Administrator.', 'Stall Construction'),
            ('Confirmed ni stallholder na pinagawa niya yung back storage room nang walang permit sa market administrator.', 'Stall Construction'),
            ('The vendor scale has no City Treasury registration seal.', 'WeightMeasures'),
            ('The stall has an illegal jumper from the water line to its sink.', 'Utilities'),
        ):
            with self.subTest(code=code):
                self.assertEqual(self.codes(text), {code})

    def test_fixed_policy_observations_and_exceptions(self):
        self.assertEqual(self.codes('Vendor handling fish without an apron.'), {'DressCode'})
        self.assertEqual(self.codes('Vendor drinking gin at the stall.'), {'Liquor'})
        self.assertEqual(self.codes('Vendor wore knee-length walking shorts and the required apron.'), set())
        self.assertEqual(self.codes('Butcher knives left on the counter after closing, no locked box.'), {'Bladed Instruments'})
        self.assertEqual(self.codes('The utensil retailer left display knives on the counter after closing, no locked box.'), set())

    def test_extinguisher_requires_established_vendor_duty(self):
        self.assertEqual(self.codes('Fire extinguisher expired, not replaced.'), set())
        self.assertEqual(self.codes('No fire extinguisher at the stall; stallholders must provide one.'), {'Stall Management'})

    def test_same_observation_changes_with_explicit_numeric_limit(self):
        for limit, expected in ((4,{'Porter Regulation'}),(7,set()),(8,set())):
            text = f'Porter pushed a wheeler loaded with seven sacks. Each porter wheeler may carry at most {limit} sacks.'
            with self.subTest(limit=limit):
                self.assertEqual(self.codes(text),expected)
        for value, expected in ((20,set()),(30,set()),(40,{'Signage & Streamers'})):
            text = f'The stall sign projected {value} cm into the aisle. Signs may not project more than 30 cm beyond the stall front.'
            with self.subTest(value=value):
                self.assertEqual(self.codes(text),expected)

    def test_prices_compare_same_quantity_and_unit(self):
        for charge, expected in ((90,set()),(100,set()),(120,{'Price Monitoring'})):
            text = f"On the inspector's test purchase, shrimp tagged P400/kg was charged P{charge} for 250 g."
            with self.subTest(charge=charge):
                self.assertEqual(self.codes(text),expected)

    def test_capacity_does_not_create_unobserved_public_disorder(self):
        text = '200 spectators packed the vendors show area. The vendors approved event allowed at most 50 spectators.'
        self.assertEqual(self.codes(text), {'Entertainment Activities'})

    def test_street_initials_and_decimals_are_not_incident_boundaries(self):
        text='Vendor selling on M. Cruz St. without a sidewalk permit; fish sold as 1.5 kg measured at 1400 g.'
        units=incident_spans(text,normalize)
        self.assertEqual(len(units),2)
        self.assertEqual(self.codes(text), {'Illegal Vendor','WeightMeasures'})

    def test_qualified_whole_description_cannot_be_reintroduced_by_fragments(self):
        text='Vendor had no vendor ID; crates blocked the exit. Neither claim was confirmed.'
        self.assertEqual(self.codes(text),set())

    def test_actor_and_category_boundaries_for_deception(self):
        text='The stallholder paid rent to a man posing as a collector; the treasurer record shows the rent unpaid.'
        self.assertEqual(self.codes(text),{'Stall Rental'})
        text='The stallholder gave the inspector a fake name and hid her ID while the citation was written.'
        self.assertEqual(self.codes(text),{'Resisting Authority'})

    def test_dirt_and_failure_words_apply_to_the_correct_object(self):
        self.assertEqual(self.codes('The vendor wore a dirty, torn shirt. Vendors must wear clean, untorn clothes.'),{'DressCode'})
        self.assertNotIn('Sanitation',self.codes('Nag-iimbak ng paninda magdamag ang may-puwesto; patay ang security light.'))

    def test_documented_permission_and_expired_order(self):
        text='The freezer uses the common outlet with written approval. Normally freezers must use their own metered outlet.'
        self.assertEqual(self.codes(text),set())
        text='The closure order was lifted yesterday; the stall is selling today.'
        self.assertEqual(self.codes(text),set())

    def test_collection_without_established_lack_of_consent_abstains(self):
        text='The seller photographed customer receipts showing phone numbers to send ads. Vendors may not collect numbers without consent.'
        self.assertEqual(self.codes(text),set())

    def test_numeric_water_window_changes_the_outcome(self):
        for hour,expected in (('6 AM',set()),('10 AM',{'Utilities'})):
            text=f'The helper was filling stall drums at the common tap at {hour}. Stalls may draw water only during the 5:00-7:00 AM allocation.'
            with self.subTest(hour=hour):
                self.assertEqual(self.codes(text),expected)

    def test_llm_nomination_cannot_bypass_the_same_positive_evidence_contract(self):
        self.assertEqual(self.codes('Uncovered yung paninda.',model=False,llm=True),{'Sanitation'})


if __name__ == '__main__':
    unittest.main()
