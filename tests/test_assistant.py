import unittest
from unittest.mock import patch
import gemini_assistant
import server

class AssistantTests(unittest.TestCase):
    def test_function_call_is_executed_then_explained(self):
        responses=[{'candidates':[{'content':{'role':'model','parts':[{'functionCall':{'name':'show_access_gaps','args':{'profile':'limited'}}}]}}]},
                   {'candidates':[{'content':{'role':'model','parts':[{'text':'These are sample points, not residents.'}]}}]}]
        with patch.object(gemini_assistant,'configuration',return_value=('dummy','gemini-2.5-flash')),patch.object(gemini_assistant,'generate',side_effect=responses) as generate:
            result=gemini_assistant.respond('Show limited mobility',lambda n,a:({'count':4},{'type':'gaps','profile':a['profile']}),{})
        self.assertEqual(result['tools_used'],['show_access_gaps'])
        self.assertEqual(result['actions'][0]['profile'],'limited')
        self.assertEqual(generate.call_count,2)

    def test_missing_key_and_unlisted_tool_fail_safely(self):
        with patch.object(gemini_assistant,'configuration',return_value=('','model')):
            with self.assertRaises(ValueError):gemini_assistant.respond('help',lambda n,a:None,{})
        response={'candidates':[{'content':{'parts':[{'functionCall':{'name':'run_shell','args':{}}}]}}]}
        with patch.object(gemini_assistant,'configuration',return_value=('dummy','model')),patch.object(gemini_assistant,'generate',return_value=response):
            with self.assertRaises(ValueError):gemini_assistant.respond('help',lambda n,a:None,{})

    def test_precise_origin_not_automatically_shared_with_model(self):
        with patch.object(server,'bootstrap',return_value={'categories':['Food assistance']}),patch.object(gemini_assistant,'respond',return_value={}) as respond:
            server.assistant_api({'message':'Help','search':{'origin':[29.123456,-82.987654]}})
        context=respond.call_args.args[2]
        self.assertNotIn('origin',context)
        self.assertNotIn('origin_name',context)

    def test_guided_story_reversal_comes_from_engine(self):
        base={'demo_story':True,'include_demo':True,'category':'Food assistance'}
        before=server.search_api(base)
        after=server.search_api({**base,'access_needs':['Step-free entrance']})
        self.assertEqual(before['matches'][0]['resource_id'],'story-near')
        self.assertEqual(after['matches'][0]['resource_id'],'story-far')
        self.assertTrue(any(r['name']=='Nearby pantry · example' for r in after['excluded']))
        self.assertTrue(all('fictional' in r['source'] for r in before['matches']))
