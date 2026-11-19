import unittest

from scripts.observed_breach_recovery import grounded_codes
from src.engine import normalize
from src.incidents import incident_spans


def codes(description):
    return {code for unit in incident_spans(description, normalize) for code in grounded_codes(unit)}


class ObservedBreachRecoveryTests(unittest.TestCase):
    def test_road_direction_needs_same_road_and_opposite_travel(self):
        rule = 'Under the posted rule, the market service road is one-way northbound only.'
        self.assertIn('Traffic', codes('The vendor drove southbound along the service road. ' + rule))
        self.assertNotIn('Traffic', codes('The vendor drove northbound along the service road. ' + rule))
        self.assertNotIn('Traffic', codes('The vendor drove southbound on the access road. ' + rule))

    def test_vehicle_limit_requires_compatible_units_and_a_strict_excess(self):
        rule = 'Under the posted rule, vehicles over 10 tonnes are prohibited on the access road.'
        self.assertIn('Traffic', codes('The vendor parked a 12 tonne truck on the access road. ' + rule))
        self.assertNotIn('Traffic', codes('The vendor parked a 10 tonne truck on the access road. ' + rule))
        self.assertNotIn('Traffic', codes('The vendor parked an 11 ton truck on the access road. ' + rule))

    def test_construction_requires_built_structure_and_explicit_approval_gap(self):
        self.assertIn('Stall Construction', codes('The vendor built a floor without approval from the Market Administrator.'))
        self.assertNotIn('Stall Construction', codes('The vendor planned to build a floor without approval from the Market Administrator.'))
        self.assertNotIn('Stall Construction', codes('The vendor built a floor with approval from the Market Administrator.'))

    def test_stall_use_requires_sales_only_condition(self):
        observation = 'The vendor was using the stall as a parking area.'
        self.assertIn('Stall Occupancy', codes(observation + ' Under the posted rule, the stall is only for selling.'))
        self.assertNotIn('Stall Occupancy', codes(observation))

    def test_public_order_requires_attributed_disruption(self):
        self.assertIn('Public Order', codes('The vendor caused a crowd and nearby stalls closed.'))
        self.assertNotIn('Public Order', codes('The vendor caused a crowd and nearby stalls kept selling.'))

    def test_scale_alteration_abstains_when_unverified(self):
        observed = 'The inspector observed that the vendor hollowed out the counterweight of the scale.'
        self.assertIn('WeightMeasures', codes(observed))
        self.assertNotIn('WeightMeasures', codes(observed + ' It was not verified.'))
