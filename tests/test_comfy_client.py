from comfyui_wrapper.workflows import builders
from tests.support import PROJECT_ROOT, comfy_graph, comfy_schema
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from comfyui_wrapper.integrations import comfy_client as cc
from comfyui_wrapper.analysis import generate
from PIL import Image
from PIL.PngImagePlugin import PngInfo


class ComfyTests(unittest.TestCase):
    def test_png_metadata_round_trip_and_pixels(self):
        image=Image.new('RGB',(32,32),'blue')
        existing=PngInfo()
        existing.add_text('prompt','{"old":true}')
        existing.add_itxt('comment','元の日本語コメント')
        raw=io.BytesIO()
        image.save(raw,format='PNG',pnginfo=existing)
        metadata={'schema':'llmpc.image.v1','analysis':{'wd_threshold':0.35,'instruction':'服を青色に'},
                  'generated_image_wd':{'predictions':[{'tag':'blue_dress','score':0.91}]}}
        with Image.open(io.BytesIO(raw.getvalue())) as source:
            result=cc.encode_png(source,metadata,workflow={'nodes':[]})
        with Image.open(io.BytesIO(result)) as restored:
            self.assertEqual(restored.tobytes(),image.tobytes())
            self.assertEqual(json.loads(restored.text['llmpc']),metadata)
            self.assertEqual(restored.text['comment'],'元の日本語コメント')
            self.assertEqual(json.loads(restored.text['prompt']),{'old':True})
            self.assertEqual(json.loads(restored.text['workflow']),{'nodes':[]})

    def test_fetch_preserves_comfy_text(self):
        info=PngInfo()
        info.add_text('prompt','{"original":true}')
        raw=io.BytesIO()
        Image.new('RGB',(8,8)).save(raw,format='PNG',pnginfo=info)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(raw.getvalue())):
            result=cc.fetch_image('http://localhost',{'filename':'x.png','type':'output'})
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(json.loads(image.text['prompt']),{'original':True})

    def test_submit_includes_metadata_for_comfy_saved_png(self):
        workflow,graph=comfy_graph()
        metadata={'schema':'llmpc.image.v1','analysis':{'wd_threshold':.4}}
        replies=[comfy_schema(graph),{'prompt_id':'p1'},
                 {'p1':{'status':{'completed':True},'outputs':{'7':{'images':[{'filename':'x.png'}]}}}}]
        with patch('comfyui_wrapper.integrations.comfy_client.api',side_effect=replies) as api:
            cc.execute('http://localhost',graph,workflow,lambda p:None,lambda s:None,metadata=metadata)
        self.assertEqual(api.call_args_list[1].args[2]['extra_data']['extra_pnginfo']['llmpc'],metadata)

    def test_conversion_for_both_families(self):
        anima = builders.patch_anima(generate.read_json(PROJECT_ROOT/'workflows/anima_template.json'),
                                    {'positive':'blue','negative':'blurry'},768,1024,1)
        for workflow in (anima,comfy_graph()[0]):
            prepared = cc.prepare(workflow)
            graph = cc.to_api(prepared)
            self.assertTrue(any(n['class_type']=='SaveImage' for n in graph.values()))
            self.assertFalse(any('control_after_generate' in n['inputs'] for n in graph.values()))
            for node in graph.values():
                for value in node['inputs'].values():
                    if isinstance(value,list):
                        self.assertIn(value[0],graph)
            cc.validate(graph,comfy_schema(graph))

    def test_validation_rejects_missing_model(self):
        workflow,graph=comfy_graph()
        info=comfy_schema(graph)
        info['CheckpointLoaderSimple']['input']['required']['ckpt_name']=[['different.safetensors']]
        with self.assertRaises(cc.ComfyError):
            cc.validate(graph,info)

    def test_submit_and_poll(self):
        workflow,graph=comfy_graph()
        images=[{'filename':'test.png','subfolder':'','type':'output'}]
        replies=[comfy_schema(graph),{'prompt_id':'p1','node_errors':{}},{},
                 {'p1':{'status':{'completed':True,'status_str':'success'},'outputs':{'7':{'images':images}}}}]
        submitted=[]
        with patch('comfyui_wrapper.integrations.comfy_client.api',side_effect=replies) as api:
            actual=cc.execute('http://localhost:8188',graph,workflow,submitted.append,lambda s:None,interval=0)
        self.assertEqual(actual,images)
        self.assertEqual(submitted,['p1'])
        self.assertEqual(api.call_args_list[1].args[1],'/prompt')
        self.assertEqual(api.call_args_list[1].args[2]['prompt'],graph)

    def test_error_and_timeout_do_not_resubmit(self):
        workflow,graph=comfy_graph()
        for ending in ({'p1':{'status':{'status_str':'error','messages':[['execution_error',{'exception_message':'OOM'}]]}}},{}):
            def api(url,route,payload=None):
                if route=='/object_info': return comfy_schema(graph)
                if route=='/prompt': return {'prompt_id':'p1'}
                return ending
            with patch('comfyui_wrapper.integrations.comfy_client.api',side_effect=api) as call:
                with self.assertRaises(cc.ComfyError):
                    cc.execute('http://localhost',graph,workflow,lambda p:None,lambda s:None,
                               timeout=.01,interval=0)
                self.assertEqual(sum(c.args[1]=='/prompt' for c in call.call_args_list),1)


if __name__=='__main__':
    unittest.main()
