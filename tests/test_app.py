"""Offline regressions for the resident-facing map workflow."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


class FinderFlowTests(unittest.TestCase):
    def test_map_first_flow_and_privacy_reset(self):
        st.cache_data.clear()
        try:
            with patch('resource_adapter.fetch_fci_resources', side_effect=RuntimeError('offline fixture')):
                app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py'), default_timeout=30).run()
                self.assertFalse(app.exception)
                chart = json.loads(app.get('deck_gl_json_chart')[0].proto.json)
                self.assertTrue(chart['layers'])
                for layer in chart['layers']:
                    if 'radiusUnits' in layer:
                        self.assertEqual(layer['radiusUnits'], 'pixels')
                    if 'widthUnits' in layer:
                        self.assertEqual(layer['widthUnits'], 'pixels')
                def control(kind, label):
                    return next(x for x in getattr(app, kind) if x.label == label)
                next(x for x in app.button if str(x.key).startswith('choose_')).click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any(x.label == '← All matches' for x in app.button))
                control('multiselect', 'Facility features needed').set_value(['Step-free entrance']).run()
                control('checkbox', 'Only confirmed facility access').check().run()
                self.assertFalse(app.exception)
                control('multiselect', 'Travel modes').set_value([]).run()
                self.assertTrue(any('Choose a travel mode' in x.value for x in app.info))
                control('selectbox', 'Starting from').set_value('Use temporary coordinates…').run()
                control('number_input', 'Latitude').set_value(29.123456).run()
                control('button', 'Clear my location').click().run()
                self.assertFalse(app.exception)
                self.assertNotIn('finder_lat', app.session_state)
                self.assertNotEqual(app.session_state['active_search']['origin'][0], 29.123456)
                self.assertNotIn('29.123456', app.session_state['search_cache']['input'])
        finally:
            st.cache_data.clear()
