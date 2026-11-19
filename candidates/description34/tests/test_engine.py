import unittest
from src.engine import catalog,normalize,analyze_ticket,process_rows,summarize_sections,load_csv
from src.reweigh import mass_in_grams
class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tax,cls.lex=catalog()
    def analyze(self,text,recorded='',verified_reweigh=None,classifier=None):
        return analyze_ticket({'ticket_id':'1','vendor_id':'1','section_id':'6','ticket_type':'Ticket',
            'issued_at':'2026-10-01T12:00:00+08:00','description':text,
            'structured_ordinance_ids':recorded,'verified_reweigh':verified_reweigh},self.tax,self.lex,classifier)
    def test_multiple_violations(self):
        base,mentions=self.analyze('Walang vendor ID, marumi ang stall, at two vendors traded punches')
        self.assertEqual({m['code'] for m in mentions},{'Vendor Identification','Sanitation','Public Order'})
        self.assertEqual(base['status'],'labeled')
    def test_negated_scale(self):
        base,mentions=self.analyze('Hindi madaya ang timbangan at malinis ang stall')
        self.assertNotIn('WeightMeasures',{m['code'] for m in mentions})
    def test_false_positive_expired_goods(self):
        _,mentions=self.analyze('Nagbebenta ng expired na de lata')
        self.assertNotIn('Permit & Licensing',{m['code'] for m in mentions})
    def test_out_of_scope(self):
        b,m=self.analyze('Nagtatapon ng tubig sa daan')
        self.assertFalse(m)
        self.assertEqual(b['status'],'no_signal')
    def test_typo(self):
        _,m=self.analyze('Madayang timbagan ang nakita sa pwesto')
        self.assertIn('WeightMeasures',{x['code'] for x in m})
    def test_duplicate(self):
        row={'ticket_id':'1','vendor_id':'23','section_id':'1','ticket_type':'Ticket','issued_at':'2026-10-01T09:00:00+08:00','description':'Walang vendor ID sa puwesto'}
        b=dict(row,ticket_id='2',issued_at='2026-10-01T11:00:00+08:00')
        txt,_,_=process_rows([row,b],self.tax,self.lex)
        self.assertEqual(txt[1]['status'],'duplicate')
    def test_description_drives_recommendation_without_ordinance_or_verification_fields(self):
        base, hits = self.analyze('Madayang timbangan at marumi ang stall', '2|4')
        self.assertEqual(base['status'], 'labeled')
        self.assertEqual({h['code'] for h in hits}, {'WeightMeasures','Sanitation'})
        self.assertTrue(all(h['review_status']=='accepted' for h in hits))

    def test_independent_observations_survive_a_mixed_description(self):
        for text, expected in (
            (
                'The seller used a scale listed as rejected in the verification register. / '
                'The helper left boxes on the stairs to the second floor.',
                {'WeightMeasures', 'Obstruction'},
            ),
            (
                'The seller used a scale listed as rejected in the verification register. '
                'The helper allegedly left boxes on the stairs.',
                {'WeightMeasures'},
            ),
            (
                'The seller used a scale listed as rejected in the verification register. '
                'The helper left boxes on the stairs. This was not confirmed.',
                {'WeightMeasures'},
            ),
            (
                'The vendor had no vendor ID. The delivery truck unloaded within the allowed window.',
                {'Vendor Identification'},
            ),
        ):
            with self.subTest(text=text):
                _, hits = self.analyze(text)
                self.assertEqual({hit['code'] for hit in hits}, expected)

    def test_short_weight_direction_and_compatible_units(self):
        for text in (
            'Fish advertised as 1 kg but measured at 850 g on the reference scale.',
            'Fish declared as 1.25 kg, measured at 1100 g.',
            'Fish sold as 1 kg pero tinimbang na 850 gramo.',
            'Fish reweighed 850 g against 1 kg sold.',
            '1 kilo declared, 880 grams measured.',
            'Beef from the stall: 500 grams on receipt, 450 g on verified scale.',
            'Fish priced for 750 g, reference scale reading 700 g after the 1 kg check weight passed.',
            'Binili ang giniling na baka bilang 500 grams. Sa Timbangan Bayan 425 g lang.',
            'Cloth sold as 4 m measured 350 cm on the reference tape.',
            'Oil sold as 2 L measured 1800 mL on a graduated measure.',
        ):
            with self.subTest(text=text):
                base, hits = self.analyze(text)
                self.assertEqual(base['status'], 'labeled')
                self.assertEqual([hit['code'] for hit in hits], ['WeightMeasures'])
                self.assertEqual(hits[0]['review_status'], 'accepted')
        class WeightModel:
            def predict(self, text):
                return [{'code':'WeightMeasures','confidence':0.999}]
        for text in (
            'Fish sold as 1 kg, measured at 1000 g.',
            'Fish reweighed 1050 g against 1 kg sold.',
            'Fish sold as 1 kg but measured at 850 mL.',
            'Cloth sold as 4 m measured 400 cm on the reference tape.',
            'Oil sold as 2 L measured 2100 mL on a graduated measure.',
            'Fish sold as 1 kg but measured at 850 g or 1 kg.',
            'Fish was measured at 850 g.',
            'Pakicheck ang timbangan.',
            'Baka madaya ang timbangan.',
            'Tampered scale?',
            'Reweigh 960 g sa 1 kilo pero sira daw ang Timbangan Bayan.',
            'Fish weighed 900 g against 1 kg; drained weight not taken.',
            'Buyer paid for 1 kg but already removed some pieces before 900 g reweigh.',
        ):
            with self.subTest(text=text):
                base, hits = self.analyze(text,classifier=WeightModel())
                self.assertEqual(base['status'], 'no_signal')
                self.assertFalse(hits)

    def test_compliant_and_uncertain_notes_cannot_trigger_model_actions(self):
        class Model:
            def __init__(self, code):
                self.code = code
            def predict(self, text):
                return [{'code':self.code,'confidence':0.999}]
        for code, text in (
            ('Traffic','The delivery truck unloaded within the allowed window.'),
            ('Promotions','The raffle had its approval number posted and the draw was public.'),
            ('Market Fees & Surcharges',"Today's market fee receipt shows full payment."),
            ('Utilities','Kalilinis lang ng grease trap at free-flowing ang drain.'),
            ('Bladed Instruments','A knife was on the counter; it is unclear whether a rule applies.'),
            ('Public Order','A crowd gathered; it is unclear whether it was a fight or a sale.'),
            ('Liquor','No alcohol was seen at the eatery, which displayed the no-liquor notice.'),
            ('Stall Construction','The renovation matched the approved plan posted at the stall.'),
            ('DressCode','The vendor wore the required apron, cap and closed shoes.'),
            ('Lighting Facilities','Gumagana yung sariling light ng stall na mine-maintain ng stallholder.'),
            ('Resisting Authority','A tip says the stall is trading during a suspension. No record has been checked.'),
            ('Stall Rental','Nagtanong yung vendor kung overdue ang rent niya. Di na-check ang ledger.'),
        ):
            with self.subTest(code=code):
                base, hits = self.analyze(text,classifier=Model(code))
                self.assertFalse(hits)
                self.assertEqual(base['status'],'no_signal')

    def test_documented_incidents_support_actions_when_model_has_no_finding(self):
        for code, text in (
            ('WeightMeasures', 'The seller used a scale listed as rejected in the verification register.'),
            ('WeightMeasures', 'Pinutol ang sealing wire ng timbangan ng tindero.'),
            ('Stall Management', 'Display goods must be covered with a tarp when it rains. The rice sacks got soaked during the rain.'),
            ('Stall Management', 'Stallholders must remove stock from the shared cold room by 8 PM. Crates were still in the shared cold room at 8:45 PM.'),
            ('Public Order', 'An intoxicated vendor broke a bottle and nearby stalls closed.'),
            ('Market Conduct', 'The seller announced a customer\'s debt to the whole row.'),
            ('Market Conduct', 'Binunot ng may-puwesto ang freezer ng katabing vendor habang wala ito.'),
        ):
            with self.subTest(code=code, text=text):
                _, hits = self.analyze(text)
                self.assertIn(code, {hit['code'] for hit in hits})

    def test_related_topics_without_an_incident_do_not_trigger_direct_actions(self):
        for text in (
            'The seller substituted a 1 kg rice pack for the advertised 5 kg rice prize.',
            'The sealing wire on the scale broke accidentally when the scale fell.',
            'Stallholders must remove stock from the cold room by 8 PM. Their crates were still in the cold room at 7:45 PM.',
            'An intoxicated vendor walked past the stall. No violations found.',
            'A buyer paid the seller a debt at the stall.',
        ):
            with self.subTest(text=text):
                _, hits = self.analyze(text)
                self.assertFalse(hits)

    def test_light_requirement_is_not_an_observation_of_compliance(self):
        class Model:
            def predict(self, text):
                return [
                    {'code':'Lighting Facilities','confidence':0.999},
                    {'code':'Stall Management','confidence':0.999},
                ]
        text = ('Patay yung number plate backlight ng stall. '
                'Dapat gumagana ang backlit number plate during trading hours.')
        _, hits = self.analyze(text,classifier=Model())
        self.assertEqual([hit['code'] for hit in hits], ['Lighting Facilities'])

    def test_temperature_comparisons_respect_minimum_and_maximum(self):
        for text, expected in (
            ("The fish chiller thermometer read 14 C, above the 4 C limit.", True),
            ("The cook held pork in a warmer at 42 C, below the 60 C minimum.", True),
            ("The fish chiller read 3 C, below the 4 C maximum.", False),
            ("Cooked pork was 65 C, above the 60 C minimum.", False),
        ):
            with self.subTest(text=text):
                _,hits = self.analyze(text)
                self.assertEqual(any(hit['code']=='Sanitation' for hit in hits),expected)

    def test_external_verification_fields_do_not_create_findings(self):
        evidence = {'declared_grams':1000,'measured_grams':850,'revision':1,
                    'scale_check_reference':'CHECK','transaction_verified':True,'conditions_verified':True}
        base, hits = self.analyze('Reference reweigh completed.',verified_reweigh=evidence)
        self.assertEqual(base['status'],'no_signal')
        self.assertFalse(hits)

    def test_reweigh_rejects_invalid_amounts_and_non_mass_units(self):
        for value, unit in (('NaN','g'),('Infinity','g'),('0','g'),('-1','g'),('20','mL')):
            with self.subTest(value=value, unit=unit), self.assertRaises(ValueError):
                mass_in_grams(value, unit)
    def test_repeated_same_code_only_one_mention(self):
        base,mentions=self.analyze('Walang vendor ID at missing vendor ID sa pwesto','3')
        self.assertEqual([m['code'] for m in mentions].count('Vendor Identification'),1)
    def test_insights_exclude_pending_and_retired_codes(self):
        rows=[{'ticket_id':'1','code':'Vendor Identification','section_id':'1','ticket_type':'Ticket',
           'issued_at':'2026-10-01T09:00:00+08:00','review_status':'pending'},
           {'ticket_id':'2','code':'WeightMeasures','section_id':'1','ticket_type':'Ticket',
           'issued_at':'2026-10-01T10:00:00+08:00','review_status':'accepted','reweigh_revision':1},
           {'ticket_id':'3','code':'WM-02','section_id':'1','ticket_type':'Ticket',
           'issued_at':'2026-10-01T11:00:00+08:00','review_status':'confirmed'},
           {'ticket_id':'4','code':'WeightMeasures','section_id':'1','ticket_type':'Ticket',
           'issued_at':'2026-10-01T11:00:00+08:00','review_status':'pending'}]
        sections=[{'section_id':'1','section_name':'Fish and Seafood Section'}]
        result=summarize_sections(rows,[],self.tax,sections)
        self.assertEqual(result[0]['prominent_code'],'WeightMeasures')
        self.assertEqual(result[0]['ticket_mentions'],1)
        self.assertEqual(result[0]['risk_score'],3)
    def test_unknown_llm_result_abstains_without_a_user_task(self):
        class FakeLLM:
            def classify(self,clean,tax):return [{'code':'OTHER','evidence':clean}]
        row={'ticket_id':'1','vendor_id':'1','section_id':'6','ticket_type':'Ticket',
            'description':'Nagtatapon ng tubig sa daan'}
        base,mentions=analyze_ticket(row,self.tax,self.lex,llm=FakeLLM())
        self.assertFalse(mentions)
        self.assertEqual(base['status'],'no_signal')
        self.assertIn('insufficient',base['review_reason'])
    def test_pii(self):
        txt=normalize('Contact test@example.com or 0917-123-4567')
        self.assertNotIn('test@example.com',txt)
        self.assertNotIn('0917',txt)
if __name__=='__main__':unittest.main()
