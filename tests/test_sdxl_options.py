from comfyui_wrapper.workflows import builders
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.workflows.sdxl_options import resolve_profile, extend_workflow, validate_loras
from comfyui_wrapper.webui import create_app


class SdxlTests(unittest.TestCase):
    def test_profiles_detect_real_filenames_and_manual_override(self):
        for name,expected in [('animagine-xl-4.0-opt.safetensors','animagine4'),
                              ('waiIllustriousSDXL_v170.safetensors','wai17'),
                              ('AnimagineXL_v31.safetensors','animagine31'),
                              ('waiIllustriousSDXL_v160.safetensors','sdxl')]:
            self.assertEqual(resolve_profile('animagine',name),expected)
        self.assertEqual(resolve_profile('animagine','renamed.safetensors','wai17'),'wai17')
        with self.assertRaises(ValueError):resolve_profile('anima','anima','wai17')

    def test_lora_chain_and_clip_skip_use_both_text_encoders(self):
        base=builders.animagine_workflow({'positive':'blue','negative':'blurry'},1024,1024,1,'model.safetensors')
        loras=validate_loras([{'name':'style.safetensors','strength_model':.6,'strength_clip':.4},
                              {'name':'detail.safetensors','strength_model':.3,'strength_clip':0}])
        workflow=extend_workflow(base,loras,2)
        graph=comfy_client.to_api(workflow)
        self.assertEqual(graph['8']['inputs']['model'],['1',0])
        self.assertEqual(graph['9']['inputs']['model'],['8',0])
        self.assertEqual(graph['9']['inputs']['clip'],['8',1])
        self.assertEqual(graph['10']['inputs']['clip'],['9',1])
        self.assertEqual(graph['10']['inputs']['stop_at_clip_layer'],-2)
        self.assertEqual(graph['5']['inputs']['model'],['9',0])
        self.assertEqual(graph['2']['inputs']['clip'],['10',0])
        self.assertEqual(graph['3']['inputs']['clip'],['10',0])
        self.assertEqual(graph['6']['inputs']['vae'],['1',2])
        self.assertEqual(len(base['nodes']),7)
        # Walk every dependency, rejecting cycles and broken links.
        def visit(nid,stack):
            self.assertNotIn(nid,stack)
            for value in graph[nid]['inputs'].values():
                if isinstance(value,list):
                    self.assertIn(value[0],graph)
                    visit(value[0],stack|{nid})
        for nid in graph:visit(nid,set())

    def test_invalid_lora_input_rejected(self):
        for value in ([{'name':'x','strength_model':float('nan')}],[{'name':'x','trigger':123}],
                      [{'name':'x'}]*4,{}):
            with self.assertRaises(ValueError):validate_loras(value)

    def test_animagine4_profile_settings_and_quality(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent.resolve()) as folder:
            client=create_app(Path(folder)/'results').test_client()
            image=io.BytesIO();Image.new('RGB',(16,16)).save(image,'PNG');image.seek(0)
            result=dict(positive='blue dress',negative='blurry',summary_ja='青',uncertainties_ja='不明')
            with patch('comfyui_wrapper.analysis.generate.analyze',return_value=result):
                response=client.post('/api/jobs',data={'image':(image,'ref.png'),'target':'animagine',
                    'checkpoint':'animagine-xl-4.0-opt.safetensors','use_quality_tags':'on'},
                    headers={'X-Requested-With':'LLMPC'})
                job=response.json['job_id'];deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    data=client.get('/api/jobs/'+job).json
                    if data['state']!='running':break
                    time.sleep(.01)
            self.assertEqual(data['state'],'done')
            self.assertTrue(data['result']['positive'].endswith('masterpiece, high score, great score, absurdres'))
            record=client.get('/api/history/'+job).json
            self.assertEqual(record['settings']['profile'],'animagine4')
            self.assertEqual(record['generation_settings']['cfg'],5)
            self.assertEqual(record['generation_settings']['steps'],28)

    def test_wai_lora_execution_metadata_history_and_restore(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent.resolve()) as folder:
            root=Path(folder)/'results'
            app=create_app(root)
            app.testing=True
            client=app.test_client()
            png=io.BytesIO();Image.new('RGB',(16,16),'blue').save(png,'PNG')
            loras=[{'name':'illustrious/style.safetensors','strength_model':.65,'strength_clip':.4,'trigger':'style_trigger'}]
            observed=[]
            def server(req,timeout=30):
                url=req if isinstance(req,str) else req.full_url
                if url.endswith('/object_info/CheckpointLoaderSimple'):
                    reply={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['waiIllustriousSDXL_v170.safetensors']]}}}}
                elif url.endswith('/object_info/LoraLoader'):
                    reply={'LoraLoader':{'input':{'required':{'lora_name':[['illustrious/style.safetensors']]}}}}
                elif url.endswith('/view?filename=generated.png&subfolder=&type=output'):
                    return io.BytesIO(png.getvalue())
                else:raise AssertionError(url)
                return io.BytesIO(json.dumps(reply).encode())
            def execute(url,graph,workflow,submitted,status,**kwargs):
                observed.append(graph)
                submitted('wai-prompt')
                return [{'filename':'generated.png','subfolder':'','type':'output'}]
            result=dict(positive='blue dress',negative='blurry',summary_ja='青い服',uncertainties_ja='不明')
            with patch('urllib.request.urlopen',side_effect=server),patch('comfyui_wrapper.analysis.generate.analyze',return_value=result) as analyze, \
                    patch('comfyui_wrapper.integrations.comfy_client.execute',side_effect=execute):
                response=client.post('/api/jobs',headers={'X-Requested-With':'LLMPC'},data={
                    'image':(io.BytesIO(png.getvalue()),'ref.png'),'target':'animagine',
                    'checkpoint':'waiIllustriousSDXL_v170.safetensors','execute':'on','loras':json.dumps(loras),'clip_skip':'2'})
                self.assertEqual(response.status_code,202)
                job=response.json['job_id']
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    status=client.get('/api/jobs/'+job).json
                    if status['state']!='running':break
                    time.sleep(.01)
            self.assertEqual(status['state'],'done')
            self.assertEqual(analyze.call_args.kwargs['profile'],'wai17')
            self.assertEqual(observed[0]['5']['inputs']['cfg'],5)
            self.assertEqual(observed[0]['8']['inputs']['lora_name'],loras[0]['name'])
            self.assertEqual(observed[0]['9']['inputs']['stop_at_clip_layer'],-2)
            self.assertIn('style_trigger',observed[0]['2']['inputs']['text'])
            response=client.get(status['downloads']['image_0.png'])
            with Image.open(io.BytesIO(response.data)) as image:
                meta=json.loads(image.text['llmpc'])['analysis']
                self.assertEqual(meta['profile'],'wai17')
                self.assertEqual(meta['loras'],loras)
                self.assertEqual(meta['clip_skip'],2)
            response.close()
            fresh=create_app(root).test_client()
            restored=fresh.get('/api/history/'+job+'/restore').json
            self.assertEqual(restored['loras'],loras)
            self.assertEqual(restored['fields']['profile'],'wai17')
            self.assertEqual(restored['generation_settings']['cfg'],5)


if __name__=='__main__':unittest.main()
