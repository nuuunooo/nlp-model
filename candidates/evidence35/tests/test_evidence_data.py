import unittest
import numpy as np
from scripts.prepare_evidence_data import audit_positive
from scripts.train_evidence_verifier import metrics
from src.evidence_verifier import features


class EvidenceDataTests(unittest.TestCase):
    def record(self,observation='The vendor built a counter without approval.',requirement='The vendor must obtain approval before construction.'):
        return {'expected_codes':['Stall Construction'],'language':'en','description':observation+' '+requirement,
                'observed_facts':['Observation: '+observation,'Requirement: '+requirement]}

    def scenario(self):
        return {'findings':[{'category':'Stall Construction','responsible_party':'stallholder',
                              'responsibility_basis':'duty','observation_id':'unapproved_work'}]}

    def test_rule_statement_does_not_supply_missing_observation(self):
        row=self.record();row['description']='The vendor must obtain approval before construction.'
        self.assertEqual(audit_positive(row,self.scenario()),'structured_observation_not_in_description')

    def test_multi_label_truth_is_not_inherited_by_sentences(self):
        row=self.record();row['expected_codes'].append('Permit & Licensing')
        self.assertEqual(audit_positive(row,self.scenario()),'multi_incident_requires_span_labels')

    def test_consent_condition_cannot_be_inferred_from_the_rule(self):
        row=self.record('The vendor photographed customer phone numbers.','The vendor must not collect numbers without consent.')
        self.assertEqual(audit_positive(row,self.scenario()),'consent_absence_only_in_requirement')

    def test_verifier_features_do_not_include_gold_or_provenance(self):
        rows=[{'description':'observation','target_code':'A','evidence_state':'supported','source_id':'fit'}]
        vectors={'observation':np.array([.2,.8])};categories={'A':np.array([.4,.6])}
        before=features(rows,vectors,categories,['A'])
        rows[0].update(evidence_state='compliant',source_id='validation',observed_facts=['DO NOT USE'])
        np.testing.assert_array_equal(before,features(rows,vectors,categories,['A']))

    def test_failed_calibration_does_not_accept_probability_one(self):
        rows=[{'evidence_state':'compliant'},{'evidence_state':'supported'}]
        result=metrics(rows,np.array([[1.,0,0],[1.,0,0]]),None)
        self.assertEqual(result['support_false_positives'],0)
        self.assertEqual(result['support_true_positives'],0)
        self.assertEqual(result['support_false_negatives'],1)


if __name__=='__main__':unittest.main()
