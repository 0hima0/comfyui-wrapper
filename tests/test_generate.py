from tests.support import PROJECT_ROOT, synthetic_anima_template
import copy
import unittest
import io
import json
from unittest.mock import patch
from pathlib import Path
import urllib.error
from comfyui_wrapper.analysis.generate import read_json, analyze, AnalysisError, apply_rating
from comfyui_wrapper.workflows.builders import patch_anima, animagine_workflow


class WorkflowTests(unittest.TestCase):
    result = {'positive':'blue dress, garden','negative':'blurry'}

    def test_rating_selection_and_conflicts(self):
        source={'positive':'safe, (sensitive:1.2), nsfw, explicit, blue dress',
                'negative':'safe, nsfw, explicit, blurry'}
        for target in ('anima','animagine'):
            for choice in ('safe','sensitive','nsfw','explicit'):
                with self.subTest(target=target,choice=choice):
                    final,meta=apply_rating(source,choice,target,[])
                    tags=[choice]
                    self.assertEqual(final['positive'],', '.join(tags+['blue dress']))
                    for tag in tags:
                        self.assertNotIn(tag,final['negative'].split(', '))
                    self.assertEqual(meta['positive_tags'],tags)
        self.assertEqual(source['positive'],'safe, (sensitive:1.2), nsfw, explicit, blue dress')

    def test_rating_replaces_all_original_spellings_with_one_tag(self):
        source={'positive':'SAFE, rating:sensitive, rating_nsfw, ((explicit:1.2)), [general], questionable\nblue dress, safe pose',
                'negative':'(rating:explicit:1.1), blurry'}
        for target in ('anima','animagine','sdxl'):
            final,meta=apply_rating(source,'explicit',target,[])
            self.assertEqual(final['positive'],'explicit, blue dress, safe pose')
            self.assertEqual(final['negative'],'blurry')
            self.assertEqual(meta['positive_tags'],['explicit'])
            self.assertEqual(len(meta['removed_positive_tags']),6)

    def test_wd_rating_mapping_and_none(self):
        for raw,expected in [('general','safe'),('sensitive','sensitive'),('questionable','nsfw'),('explicit','explicit')]:
            final,meta=apply_rating(self.result,'auto','anima',[
                {'category':0,'tag':'blue_dress','score':.99},
                {'category':9,'tag':raw,'score':.9}])
            self.assertEqual(meta['resolved'],expected)
            self.assertTrue(final['positive'].startswith(expected+', '))
        self.assertEqual(apply_rating(self.result,'none','anima',[])[0],self.result)
        with self.assertRaises(ValueError):
            apply_rating(self.result,'auto','anima',[])

    def validate_links(self, workflow):
        nodes = {n['id']:n for n in workflow['nodes']}
        for link, source, slot, target, input_slot, kind in workflow['links']:
            self.assertIn(link, nodes[source]['outputs'][slot]['links'])
            self.assertEqual(nodes[target]['inputs'][input_slot]['link'], link)
            self.assertEqual(nodes[target]['inputs'][input_slot]['type'], kind)

    def test_anima_preserves_model_and_connections(self):
        template = synthetic_anima_template()
        original = copy.deepcopy(template)
        changed = patch_anima(template,self.result,768,1024,123)
        nodes = {n['id']:n for n in changed['nodes']}
        self.assertEqual(template,original)
        self.assertEqual(changed['links'],template['links'])
        self.assertEqual(nodes[11]['widgets_values'],[self.result['positive']])
        self.assertEqual(nodes[11]['widgets_values_named']['text'],self.result['positive'])
        self.assertEqual(nodes[19]['widgets_values'][0:2],[123,'fixed'])
        self.assertEqual(nodes[19]['widgets_values'][2:],next(n for n in original['nodes'] if n['id']==19)['widgets_values'][2:])
        self.assertEqual(nodes[28]['widgets_values'],[768,1024,1])
        self.assertEqual(nodes[44],next(n for n in template['nodes'] if n['id']==44))
        self.validate_links(changed)

    def test_animagine_has_separate_sdxl_graph(self):
        workflow = animagine_workflow(self.result,1024,1024,123,'test.safetensors')
        self.validate_links(workflow)
        self.assertEqual(workflow['nodes'][0]['type'],'CheckpointLoaderSimple')
        self.assertEqual(workflow['nodes'][0]['widgets_values'],['test.safetensors'])
        self.assertNotIn('UNETLoader',[n['type'] for n in workflow['nodes']])

    def test_wrong_anima_template_rejected(self):
        with self.assertRaises(ValueError):
            patch_anima({'nodes':[]},self.result,1024,1024,1)

    def test_ollama_request_and_response(self):
        from PIL import Image
        result = dict(self.result, summary_ja='青い服', uncertainties_ja='人物名は不明')
        response = {'done': True, 'message': {'content': json.dumps(result)}}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as call:
            actual = analyze(Image.new('RGB',(32,32)), '服を青に', 'red_dress',
                             'http://localhost:11434', 'qwen3-vl:8b','anima')
        self.assertEqual(actual,result)
        payload = json.loads(call.call_args.args[0].data)
        self.assertEqual(payload['keep_alive'],0)
        self.assertEqual(payload['model'],'qwen3-vl:8b')
        self.assertFalse(payload['think'])
        self.assertEqual(payload['options']['num_predict'],4096)
        self.assertTrue(payload['messages'][1]['images'][0])
        self.assertEqual(json.loads(payload['messages'][1]['content'])['user_instruction'],'服を青に')

    def test_truncated_response_rejected(self):
        from PIL import Image
        response = {'done':True,'done_reason':'length','message':{'content':'{}'}}
        with patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps(response).encode()) for _ in range(2)]):
            with self.assertRaisesRegex(AnalysisError,'done_reason'):
                analyze(Image.new('RGB',(8,8)),'','','http://localhost:11434','qwen3-vl:8b','anima')

    def test_length_retry_preserves_instruction_and_increases_budget(self):
        from PIL import Image
        result=dict(self.result,summary_ja='青い服',uncertainties_ja='不明')
        replies=[{'done':True,'done_reason':'length','eval_count':4096,'message':{'content':'{'}},
                 {'done':True,'done_reason':'stop','message':{'content':json.dumps(result)}}]
        with patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps(r).encode()) for r in replies]) as call:
            actual=analyze(Image.new('RGB',(1600,1200)),'服を青に',','.join('tag'+str(i) for i in range(300)),
                           'http://localhost:11434','qwen3-vl:8b','anima')
        self.assertEqual(actual,result)
        first,second=[json.loads(c.args[0].data) for c in call.call_args_list]
        self.assertEqual(second['options']['num_predict'],8192)
        self.assertEqual(first['options']['num_ctx'],16384)
        self.assertEqual(second['options']['num_ctx'],first['options']['num_ctx'])
        user=json.loads(second['messages'][1]['content'])
        self.assertEqual(user['user_instruction'],'服を青に')
        self.assertEqual(len(user['candidate_wd_tags'].split(',')),40)

    def test_invalid_json_and_empty_prompt_retried_once(self):
        from PIL import Image
        valid=dict(self.result,summary_ja='説明',uncertainties_ja='不明')
        for bad in ('{', '[]', json.dumps(dict(valid,positive=''))):
            responses=[{'done':True,'message':{'content':bad}},
                       {'done':True,'message':{'content':json.dumps(valid)}}]
            with self.subTest(bad=bad),patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps(r).encode()) for r in responses]) as call:
                self.assertEqual(analyze(Image.new('RGB',(8,8)),'','','http://localhost','model','anima'),valid)
                self.assertEqual(call.call_count,2)

    def test_unsupported_think_compatibility(self):
        from PIL import Image
        result=dict(self.result,summary_ja='説明',uncertainties_ja='不明')
        error=urllib.error.HTTPError('http://localhost',400,'Bad Request',{},io.BytesIO(b'{"error":"model does not support thinking"}'))
        response=io.BytesIO(json.dumps({'done':True,'message':{'content':json.dumps(result)}}).encode())
        with patch('urllib.request.urlopen',side_effect=[error,response]) as call:
            self.assertEqual(analyze(Image.new('RGB',(8,8)),'','','http://localhost','model','anima'),result)
        self.assertNotIn('think',json.loads(call.call_args_list[1].args[0].data))

    def test_http_error_does_not_retry(self):
        from PIL import Image
        error=urllib.error.HTTPError('http://localhost',404,'Not Found',{},io.BytesIO(b'model missing'))
        with patch('urllib.request.urlopen',side_effect=error) as call:
            with self.assertRaisesRegex(AnalysisError,'404'):
                analyze(Image.new('RGB',(8,8)),'','','http://localhost','model','anima')
        self.assertEqual(call.call_count,1)


if __name__ == '__main__':
    unittest.main()
