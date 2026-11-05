"""Explicit model/folder associations override legacy family hints safely."""
import copy
import tempfile
import unittest
from pathlib import Path
from comfyui_wrapper.models.model_families import validate_checkpoint_lora_folders,allowed_lora
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.settings.app_config import DEFAULTS
from comfyui_wrapper.settings.config_editor import ConfigEditor

class CheckpointFolderTests(unittest.TestCase):
    def test_arbitrary_folders_multiple_models_nested_and_boundaries(self):
        mapping=validate_checkpoint_lora_folders({'models/custom.safetensors':['Custom/characters','Shared'], 'other.safetensors':['other'], 'off.safetensors':[]})
        def allowed(model,name,family='unknown'):return allowed_lora('animagine',model,family,name,mapping=mapping)
        self.assertTrue(allowed('models/custom.safetensors','Custom/characters/sub/a.safetensors'))
        self.assertTrue(allowed('models\\custom.safetensors','Shared\\style.safetensors'))
        self.assertFalse(allowed('models/custom.safetensors','Custom/characters2/a.safetensors'))
        self.assertFalse(allowed('models/custom.safetensors','other/a.safetensors'))
        self.assertFalse(allowed('off.safetensors','sdxl/a.safetensors','sdxl'))
        self.assertTrue(allowed('unmapped.safetensors','sdxl/a.safetensors','sdxl'))
        self.assertFalse(allowed_lora('anima','models/custom.safetensors','anima','Shared/a',mapping=mapping))
        self.assertTrue(allowed_lora('animagine','root','unknown','a',mapping={'root':['.']}))
        self.assertFalse(allowed_lora('animagine','root','unknown','nested/a',mapping={'root':['.']}))

    def test_validation_rejects_traversal_absolute_and_ambiguous_paths(self):
        for value in [[],{'model':'folder'},{'model':['../outside']},{'../model':['folder']},{'model':['/absolute']},{'model':['folder/../other']},{'MODEL':['a'],'model':['b']},{'model':['a\nb']}]:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_checkpoint_lora_folders(value)

    def test_settings_roundtrip_and_runtime_metadata(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder);path=root/'synthetic-settings.json';editor=ConfigEditor(path)
            state=editor.read();data=copy.deepcopy(state['settings']);data['checkpoint_lora_folders']={'custom.safetensors':['my-folder']}
            preview=editor.review(data,state['revision']);editor.save(data,state['revision'],preview['confirmation'])
            self.assertEqual(editor.read()['settings']['checkpoint_lora_folders'],data['checkpoint_lora_folders'])
            app=create_app(root/'data',checkpoint_lora_folders=data['checkpoint_lora_folders'])
            entry=app.extensions['app_services'].catalog.classify('animagine','custom.safetensors')
            self.assertEqual(entry['family'],'unknown');self.assertEqual(entry['lora_folders'],['my-folder'])

    def test_submission_uses_server_rules_not_forged_family(self):
        import json
        from unittest.mock import patch
        from tests.support import wait_for_completion
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            app=create_app(Path(folder),checkpoint_lora_folders={'custom.safetensors':['arbitrary']});client=app.test_client();headers={'X-Requested-With':'LLMPC'}
            form=dict(target='animagine',checkpoint='custom.safetensors',instruction='a park',model_family='sdxl',loras=json.dumps([dict(name='sdxl/not-allowed.safetensors')]))
            self.assertEqual(client.post('/api/jobs',data=form,headers=headers).status_code,400)
            form['loras']=json.dumps([dict(name='arbitrary/style.safetensors')])
            with patch('comfyui_wrapper.analysis.generate.analyze',return_value=dict(positive='park',negative='text',summary_ja='公園',uncertainties_ja='')):
                reply=client.post('/api/jobs',data=form,headers=headers);self.assertEqual(reply.status_code,202,reply.json)
                record=wait_for_completion(client,'/api/jobs/'+reply.json['job_id'],app)
            self.assertEqual(record['state'],'done')
            self.assertEqual(record['settings']['loras'][0]['name'],'arbitrary/style.safetensors')
