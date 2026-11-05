import copy
import io
import json
import unittest
from unittest.mock import patch
from PIL import Image
from comfyui_wrapper.analysis import analysis_response as bounded
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.infrastructure import job_control


class ResponseBoundsTests(unittest.TestCase):
    result=dict(summary_ja='人物',positive='red jacket, black trousers',negative='blurry',uncertainties_ja='')

    def tearDown(self):
        job_control.local.control=None

    def test_schema_and_local_validation_use_character_limits(self):
        schema=bounded.schema(bounded.LIMITS)
        self.assertEqual(bounded.parse(json.dumps(self.result),schema),self.result)
        for key,maximum in bounded.LIMITS.items():
            with self.subTest(key=key):
                content=json.dumps(dict(self.result,**{key:'字'*(maximum+1)}))
                with self.assertRaisesRegex(ValueError,'文字数上限'):bounded.parse(content,schema)
        for content in (json.dumps(dict(self.result,extra='unexpected')),
                        '{"positive":"first",'+json.dumps(self.result)[1:],
                        json.dumps(dict(self.result,positive='blue dress, blue dress, blue dress'))):
            with self.assertRaises(ValueError):bounded.parse(content,schema)

    def test_overlong_complete_reply_retries_without_truncating_user_instruction(self):
        replies=[dict(done=True,message=dict(content=json.dumps(dict(self.result,positive='x'*18000)))),
                 dict(done=True,message=dict(content=json.dumps(self.result)))]
        seen=[]
        def chat(url,payload):
            seen.append(copy.deepcopy(payload));return replies[len(seen)-1]
        instruction='画像1の人物と画像2の人物を同じ庭に配置する。'*100
        with patch('comfyui_wrapper.analysis.generate._chat',side_effect=chat):
            result=generate.analyze(Image.new('RGB',(8,8)),instruction,'','url','model','anima')
        self.assertEqual(result,self.result)
        self.assertEqual(len(seen),2)
        self.assertLess(seen[1]['format']['properties']['positive']['maxLength'],seen[0]['format']['properties']['positive']['maxLength'])
        self.assertEqual(json.loads(seen[1]['messages'][1]['content'])['user_instruction'],instruction)
        self.assertIn('maxLength',seen[1]['messages'][0]['content'])
        self.assertGreater(seen[0]['options']['repeat_penalty'],1)

    def test_stream_stops_when_complete_valid_object_arrives(self):
        job_control.local.control=job_control.JobControl()
        class Stream(io.BytesIO):
            def __init__(self,raw):super().__init__(raw);self.reads=0
            def __next__(self):
                self.reads+=1
                if self.reads>1:raise AssertionError('should close before trailing output')
                return super().__next__()
        raw=json.dumps(dict(done=False,message=dict(content=json.dumps(self.result)+' '*200)))+'\n'
        stream=Stream(raw.encode())
        with patch('urllib.request.urlopen',return_value=stream):
            reply=generate._chat('http://ollama',dict(model='test',format=bounded.schema(bounded.LIMITS)))
        self.assertTrue(reply['done']);self.assertEqual(reply['done_reason'],'structured_complete')
        self.assertTrue(stream.closed)
        self.assertEqual(bounded.parse(reply['message']['content'],bounded.schema(bounded.LIMITS)),self.result)

    def test_runaway_stream_is_closed_and_retried_instead_of_used(self):
        job_control.local.control=job_control.JobControl()
        bad=io.BytesIO((json.dumps(dict(done=False,message=dict(content='{"positive":"'+('red jacket, '*80))))+'\n').encode())
        good=io.BytesIO((json.dumps(dict(done=True,done_reason='stop',message=dict(content=json.dumps(self.result))))+'\n').encode())
        with patch('urllib.request.urlopen',side_effect=[bad,good]) as call:
            result=generate.analyze(Image.new('RGB',(8,8)),'庭で並ぶ','','http://ollama','model','anima')
        self.assertEqual(result,self.result);self.assertEqual(call.call_count,2)
        self.assertTrue(bad.closed);self.assertTrue(good.closed)

    def test_nonrepeated_overflow_and_incomplete_stream_are_not_accepted(self):
        job_control.local.control=job_control.JobControl()
        text='{"positive":"'+''.join(f'tag{i},' for i in range(2500))
        stream=io.BytesIO((json.dumps(dict(done=False,message=dict(content=text)))+'\n').encode())
        with patch('urllib.request.urlopen',return_value=stream):
            reply=generate._chat('http://ollama',dict(model='test',format=bounded.schema(bounded.LIMITS)))
        self.assertFalse(reply['done']);self.assertEqual(reply['done_reason'],'response_guard')
        self.assertTrue(stream.closed)
        self.assertIn('長すぎる',reply['response_issue'])

    def test_two_guard_failures_never_return_partial_prompt(self):
        job_control.local.control=job_control.JobControl()
        raw=(json.dumps(dict(done=False,message=dict(content='{"positive":"'+('jacket, '*90))))+'\n').encode()
        with patch('urllib.request.urlopen',side_effect=[io.BytesIO(raw),io.BytesIO(raw)]) as call:
            with self.assertRaisesRegex(generate.AnalysisError,'反復'):
                generate.analyze(Image.new('RGB',(8,8)),'','','http://ollama','model','anima')
        self.assertEqual(call.call_count,2)
