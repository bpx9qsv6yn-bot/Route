"""Contract tests for the desktop API, without external directory requests."""
import json
import unittest
from unittest.mock import patch
import pandas as pd
import server


class DesktopApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=pd.read_csv(server.DATA/'resources.csv',dtype=str).fillna('').to_dict('records')

    def setUp(self):
        self.source=patch.object(server,'catalog',return_value=(self.records,{'status':'fallback'}))
        self.source.start()
        self.addCleanup(self.source.stop)

    def test_invalid_preferences_are_rejected(self):
        for payload in ({'origin':[float('nan'),0]},{'modes':[]},{'max_minutes':0},{'max_walk':10},{'sort':'fake'}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                server.validate_search(payload)

    def test_search_and_selected_journey_are_serializable_and_consistent(self):
        request={'category':'All resource types','max_minutes':90}
        result=server.search_api(request)
        self.assertTrue(result['matches'])
        row=result['matches'][0]
        journey=server.journey_api({**request,'resource_id':row['resource_id']})
        self.assertEqual(row['resource_id'],journey['resource']['resource_id'])
        self.assertEqual(row['best_option']['minutes'],journey['resource']['best_option']['minutes'])
        self.assertTrue(journey['legs'])
        self.assertIn('FAIRROUTE',journey['summary'])
        json.dumps(journey,allow_nan=False)

    def test_query_and_unavailable_resource(self):
        self.assertEqual(server.search_api({'query':'no-such-service-128347'})['matches'],[])
        with self.assertRaises(ValueError):
            server.journey_api({'resource_id':'not-a-resource'})

    def test_changing_travel_mode_recomputes_burden(self):
        request={'category':'All resource types','max_minutes':90,'modes':['Walk','RTS bus','Bike / micromobility']}
        rows=server.search_api(request)['matches']
        row=next(r for r in rows if len(r['options'])>1)
        for option in row['options']:
            journey=server.journey_api({**request,'resource_id':row['resource_id'],'option_index':option['index']})
            self.assertEqual(journey['resource']['best_option']['mode'],option['mode'])
            self.assertEqual(journey['resource']['burden']['points'],option['burden']['points'])

    def test_profile_and_scenario_validation(self):
        with self.assertRaises(ValueError): server.gaps_api('Food assistance','invalid')
        with self.assertRaises(ValueError): server.scenario_api('invalid')

if __name__=='__main__': unittest.main()

class AccessEvidenceTests(unittest.TestCase):
    def test_unknown_is_not_verified_even_without_selected_needs(self):
        from access_evidence import access_evidence, verification_checklist
        from types import SimpleNamespace
        resource={'name':'Example','source':'Florida Community Resource Map','resource_id':'example','step_free':'unknown'}
        evidence=access_evidence(resource,{'access_needs':[],'wheelchair_transit':False},SimpleNamespace(mode='Walk'))
        self.assertEqual(evidence['fields'][0]['state'],'unknown')
        self.assertEqual(evidence['required_unknown'],0)
        self.assertTrue(any('step-free' in q for q in evidence['questions']))
        checklist=verification_checklist(resource,evidence)
        self.assertIn('No update has been submitted',checklist)
        self.assertNotIn('29.',checklist)

    def test_required_unknown_and_demo_evidence_are_explicit(self):
        from access_evidence import access_evidence
        from types import SimpleNamespace
        evidence=access_evidence({'source':'FairRoute demonstration data','step_free':'yes'},
            {'access_needs':['Accessible restroom'],'wheelchair_transit':True},SimpleNamespace(mode='RTS',accessibility_uncertain=True))
        self.assertTrue(evidence['demo'])
        self.assertEqual(evidence['required_unknown'],2)
        self.assertEqual(evidence['fields'][0]['status'],'Reported available')

    def test_station_preset_matches_official_stop(self):
        station=next(l for l in server.locations() if l['location_id']=='rosa-parks')
        stop=server.router().stops['1']
        self.assertAlmostEqual(station['latitude'],stop['lat'],places=5)
        self.assertAlmostEqual(station['longitude'],stop['lon'],places=5)

    def test_live_failure_uses_timestamped_public_snapshot(self):
        server.catalog.cache_clear()
        with patch.object(server,'fetch_fci_resources',side_effect=OSError('Offline')):
            records,metadata=server.catalog()
        server.catalog.cache_clear()
        self.assertEqual(metadata['status'],'snapshot')
        self.assertTrue(metadata['fetched_at'])
        self.assertTrue(any('demonstration' not in r['source'].lower() for r in records))
