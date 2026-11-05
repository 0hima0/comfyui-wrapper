"""Text-only submission, Ollama payload and durable generation artifacts."""
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.analysis import analysis_reuse
from comfyui_wrapper.generation.reference_images import load_references


class TextGenerationTests(unittest.TestCase):
    def test_empty_references_still_validate_metadata(self):
        self.assertEqual(load_references([], '[]'), [])
        with self.assertRaises(ValueError):
            load_references([], '[{"id":1}]')

    def test_text_generation_and_prompt_only(self):
        for execute in (False, True):
            with self.subTest(execute=execute), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
                root=Path(folder)/'results'
                client=create_app(root).test_client()
                captured=[]
                def chat(url,payload):
                    captured.append(payload)
                    return {'done':True,'message':{'content':json.dumps(dict(
                        positive='person, park, sunset',negative='blurry',
                        summary_ja='夕暮れの公園',uncertainties_ja=''))}}
                image=io.BytesIO()
                Image.new('RGB',(16,16),'green').save(image,'PNG')
                info={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['example.safetensors']]}}}}
                form=dict(target='animagine',checkpoint='example.safetensors',
                          instruction='夕暮れの公園に立つ人物',additional_positive='red coat',
                          additional_negative='text',use_wd='on',rating='auto',preserve_people='on',reference_info='[]')
                if execute:form['execute']='on'
                with patch('comfyui_wrapper.analysis.generate._chat',side_effect=chat), \
                     patch('urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(json.dumps(info).encode())), \
                     patch('comfyui_wrapper.integrations.comfy_client.execute',return_value=[dict(filename='sample.png',subfolder='',type='output')]), \
                     patch('comfyui_wrapper.integrations.comfy_client.fetch_image',return_value=image.getvalue()), \
                     patch('comfyui_wrapper.analysis.wd_tagger.wd_tags') as tagger:
                    response=client.post('/api/jobs',data=form,headers={'X-Requested-With':'LLMPC'})
                    self.assertEqual(response.status_code,202,response.json)
                    job=response.json['job_id']
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        result=client.get('/api/jobs/'+job).json
                        if result['state']!='running':break
                        time.sleep(.01)
                    self.assertEqual(result['state'],'done',result)
                    tagger.assert_not_called()
                self.assertNotIn('images',captured[0]['messages'][1])
                self.assertIn('No reference images',captured[0]['messages'][0]['content'])
                self.assertEqual(result['settings']['input_images'],[])
                self.assertIsNone(result['settings']['input_image'])
                self.assertFalse(result['settings']['use_wd'])
                self.assertFalse(result['settings']['preserve_people'])
                report=json.loads((root/job/'analysis.json').read_text(encoding='utf-8'))
                self.assertEqual(report['reference_mode'],'text_only')
                reused=analysis_reuse.restore(report,report['reuse_fingerprint'],'park, red coat','text',job)
                self.assertEqual(reused['reference_images'],[])
                self.assertEqual(reused['result']['positive'],'park, red coat')
                self.assertIsNone(report['wd_reference_id'])
                self.assertIn('red coat',report['result']['positive'])
                self.assertIn('text',report['result']['negative'])
                if execute:self.assertEqual(len(result['images']),1)

    def test_empty_request_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            client=create_app(Path(folder)/'results').test_client()
            response=client.post('/api/jobs',data={'target':'animagine'},headers={'X-Requested-With':'LLMPC'})
            self.assertEqual(response.status_code,400)
            self.assertIn('指示または追加Positive',response.json['error'])