import unittest

from scripts.scoped_recovery_evidence import additional_proofs
from src.engine import normalize
from src.incidents import incident_spans


def codes(description):
    return {code for unit in incident_spans(description, normalize) for code in additional_proofs(unit)}


class ScopedRecoveryEvidenceTests(unittest.TestCase):
    def test_exit_path_requires_vendor_placement_and_actual_obstruction(self):
        self.assertIn('Obstruction', codes('The vendor stacked crates across the emergency exit.'))
        self.assertNotIn('Obstruction', codes('The vendor stacked crates beside the emergency exit.'))
        self.assertNotIn('Obstruction', codes('The vendor never stacked crates across the emergency exit.'))

    def test_shared_fixture_requires_vendor_duty_and_current_failure(self):
        observation = 'The shared light is broken.'
        duty = 'Under the row agreement, this stallholder must maintain the shared light.'
        self.assertIn('Lighting Facilities', codes(observation + ' ' + duty))
        self.assertNotIn('Lighting Facilities', codes(observation))
        self.assertNotIn('Lighting Facilities', codes('The shared light is working now. ' + duty))

    def test_trading_requires_an_active_order(self):
        self.assertIn('General Penalties', codes('The vendor was still suspended but sold fruit.'))
        self.assertNotIn('General Penalties', codes('The vendor sold fruit after the suspension ended.'))
        self.assertNotIn('General Penalties', codes('The vendor was still suspended and did not sell fruit.'))

    def test_shortfall_checks_units_and_observed_quantity(self):
        self.assertIn('WeightMeasures', codes('The inspector checked ribbon sold as 2 m, measured 180 cm.'))
        self.assertNotIn('WeightMeasures', codes('The inspector checked ribbon sold as 2 m, measured 200 cm.'))
        self.assertNotIn('WeightMeasures', codes('The customer claimed ribbon sold as 2 m, only 180 cm.'))
        self.assertNotIn('WeightMeasures', codes('Ribbon sold as 2 m, measured 180 cm. It was not verified.'))
