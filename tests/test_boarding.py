import unittest
from fairroute import TransitRouter

class BoardingTests(unittest.TestCase):
    def router(self,boarding='yes',arrival='yes'):
        return TransitRouter({'routes':[{'id':'1','short_name':'1','wheelchair':'yes','headway_minutes':10}],
            'stops':[{'id':'a','name':'A','lat':29.65,'lon':-82.32,'wheelchair':boarding},
                     {'id':'b','name':'B','lat':29.67,'lon':-82.32,'wheelchair':arrival}],
            'edges':[{'from':'a','to':'b','route':'1','minutes':5}]})
    def trip(self,router,required=True):
        return router.option_to(router.build_plan((29.65,-82.32),.1,3,wheelchair_needed=required),(29.67,-82.32))
    def test_known_inaccessible_boarding_and_arrival_excluded(self):
        self.assertIsNone(self.trip(self.router(boarding='no')))
        self.assertIsNone(self.trip(self.router(arrival='no')))
        self.assertIsNotNone(self.trip(self.router(boarding='no'),False))
    def test_unknown_stop_is_flagged_even_if_vehicle_is_accessible(self):
        self.assertTrue(self.trip(self.router(arrival='unknown')).accessibility_uncertain)
        self.assertFalse(self.trip(self.router()).accessibility_uncertain)
