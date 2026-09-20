"""Explicitly fictional provider facts over real modeled transit, for a repeatable demo."""

def resources():
    base=dict(category='Food assistance',categories='Food assistance',accessible_restroom='unknown',hours='Illustrative service; not an operating provider.',phone='',website='',source='FairRoute demonstration · fictional provider',source_checked='',location_precision='illustrative',service_format='illustrative',source_id='',description='Fictional pantry used to explain access constraints. Travel estimates use the bundled Gainesville network.',accessibility_notes='Invented entrance facts for the guided example, not verified facts about a real place.')
    return [dict(base,resource_id='story-near',name='Nearby pantry · example',latitude=29.6485,longitude=-82.3227,address='Illustrative location A',step_free='no'),
            dict(base,resource_id='story-far',name='Farther pantry · example',latitude=29.661,longitude=-82.3227,address='Illustrative location B',step_free='yes')]
