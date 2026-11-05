import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from comfyui_wrapper.models import model_families as families
from comfyui_wrapper.webui import create_app


class FamilyTests(unittest.TestCase):
    def test_model_api_exposes_family_and_configuration_has_priority(self):
        names=['sd15/custom.safetensors','sdxl/custom.safetensors',
               'waiIllustriousSDXL_v170.safetensors','renamed.safetensors']
        def server(url,timeout=5):
            if url.endswith('UNETLoader'):
                return io.BytesIO(json.dumps({'UNETLoader':{'input':{'required':{'unet_name':[[]]}}}}).encode())
            return io.BytesIO(json.dumps({'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[names]}}}}).encode())
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            client=create_app(Path(folder),checkpoint_families={'renamed.safetensors':'illustrious'}).test_client()
            with patch('urllib.request.urlopen',side_effect=server):
                data=client.get('/api/models').json
        rows={row['name']:row for row in data['models']}
        self.assertEqual(rows[names[0]]['family'],'sd15')
        self.assertEqual(rows[names[0]]['profile'],'sd15')
        self.assertEqual(rows[names[1]]['family'],'sdxl')
        self.assertEqual(rows[names[2]]['family'],'illustrious')
        self.assertEqual(rows[names[3]]['family_source'],'config')
        self.assertIn('[Illustrious (SDXL)]',rows[names[3]]['label'])

    def test_checkpoint_classification_and_explicit_override(self):
        examples = [('sd15/custom.safetensors', 'sd15'),
                    ('sdxl/custom.safetensors', 'sdxl'),
                    ('sdxl/waiIllustriousSDXL_v170.safetensors', 'illustrious'),
                    ('illustrious/custom.safetensors', 'illustrious'),
                    ('AnimagineXL_v31.safetensors', 'sdxl'),
                    ('v1-5-pruned-emaonly.safetensors', 'sd15'),
                    ('custom.safetensors', 'unknown')]
        for name, expected in examples:
            self.assertEqual(families.checkpoint_family('animagine', name)[0], expected)
        self.assertEqual(families.checkpoint_family('animagine', 'renamed.safetensors',
                         {'renamed.safetensors':'illustrious'}), ('illustrious','config'))
        self.assertEqual(families.checkpoint_family('anima','sdxl/model.safetensors')[0], 'anima')

    def test_lora_folders_nested_case_and_windows_paths(self):
        self.assertTrue(families.compatible('illustrious', 'illustrious/characters/a.safetensors'))
        self.assertTrue(families.compatible('sd15', r'SD15\style\a.safetensors'))
        self.assertTrue(families.compatible('sdxl', 'sdxl/a.safetensors'))
        self.assertFalse(families.compatible('illustrious', 'sdxl/a.safetensors'))
        self.assertFalse(families.compatible('sdxl', 'illustrious/a.safetensors'))
        self.assertFalse(families.compatible('sd15', 'a.safetensors'))
        self.assertFalse(families.compatible('unknown', 'sd15/a.safetensors'))
        self.assertEqual(families.folder_family('custom/deeper/a.safetensors', {'custom':'sd15'}),'sd15')

    def test_server_rejects_mismatch_even_without_execution_and_ignores_forged_family(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            client = create_app(Path(folder)).test_client()
            for checkpoint, name in [('waiIllustriousSDXL_v170.safetensors','sdxl/a.safetensors'),
                                     ('sd15/model.safetensors','illustrious/a.safetensors'),
                                     ('unknown.safetensors','sd15/a.safetensors'),
                                     ('sdxl/model.safetensors','unclassified.safetensors')]:
                response = client.post('/api/jobs', headers={'X-Requested-With':'LLMPC'}, data={
                    'target':'animagine', 'checkpoint':checkpoint, 'model_family':'sdxl', 'instruction':'a park',
                    'loras':json.dumps([{'name':name}])})
                self.assertEqual(response.status_code,400)
                self.assertIn('許可されたLoRAフォルダーではありません', response.json['error'])

    def test_options_keep_all_loras_for_management_and_provide_classification(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            client=create_app(Path(folder)).test_client()
            def api(url, endpoint, timeout=5):
                if endpoint.endswith('LoraLoader'):
                    return {'LoraLoader':{'input':{'required':{'lora_name':[['sd15/a','sdxl/b','illustrious/c','root']]}}}}
                return {'KSampler':{'input':{'required':{'sampler_name':[['euler']], 'scheduler':[['normal']]}}}}
            with patch('comfyui_wrapper.integrations.comfy_client.api',side_effect=api):
                data=client.get('/api/generation-options').json
            self.assertEqual(len(data['loras']),4)
            self.assertEqual([row['family'] for row in data['lora_options']], ['sd15','sdxl','illustrious','unknown'])

    def test_sd15_matching_lora_saved_in_workflow_history_and_restore(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            client=create_app(Path(folder)).test_client()
            image=io.BytesIO();Image.new('RGB',(16,16)).save(image,'PNG');image.seek(0)
            result=dict(positive='blue dress',negative='blurry',summary_ja='青',uncertainties_ja='不明')
            with patch('comfyui_wrapper.analysis.generate.analyze',return_value=result):
                response=client.post('/api/jobs',headers={'X-Requested-With':'LLMPC'},data={
                    'target':'animagine','checkpoint':'sd15/model.safetensors','image':(image,'reference.png'),
                    'loras':json.dumps([{'name':'sd15/style.safetensors','trigger':'style_token'}])})
                self.assertEqual(response.status_code,202)
                job=response.json['job_id'];deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    data=client.get('/api/jobs/'+job).json
                    if data['state']!='running':break
                    time.sleep(.01)
            self.assertEqual(data['state'],'done')
            self.assertIn('style_token',data['result']['positive'])
            history=client.get('/api/history/'+job).json
            self.assertEqual(history['settings']['model_family']['family'],'sd15')
            self.assertEqual(history['settings']['profile'],'sd15')
            self.assertEqual(client.get('/api/history/'+job+'/restore').json['loras'][0]['name'],'sd15/style.safetensors')


if __name__ == '__main__': unittest.main()
