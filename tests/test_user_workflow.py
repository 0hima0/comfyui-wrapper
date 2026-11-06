"""Anima is optional: no test reads or redistributes an acquired workflow."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tests.support import PROJECT_ROOT, synthetic_anima_template
from comfyui_wrapper.workflows import builders
from comfyui_wrapper.models.model_catalog import ModelCatalog
from comfyui_wrapper.system import preflight
from comfyui_wrapper.webui import create_app


class UserWorkflowTests(unittest.TestCase):
    def setUp(self):
        (PROJECT_ROOT/'tmp-test-runtime').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT_ROOT/'tmp-test-runtime')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'workflows/anima_template.json'

    def test_missing_file_has_actionable_message(self):
        with self.assertRaisesRegex(ValueError,'workflows/README.md'):
            builders.load_anima_template(self.path)

    def test_exported_ui_json_does_not_need_custom_named_widgets(self):
        workflow=synthetic_anima_template()
        for node in workflow['nodes']:
            node.pop('widgets_values_named',None)
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(workflow),encoding='utf-8')
        template=builders.load_anima_template(self.path)
        changed=builders.patch_anima(template,{'positive':'scene','negative':'text'},768,1024,123,'selected.safetensors')
        by_id={n['id']:n for n in changed['nodes']}
        self.assertEqual(by_id[45]['widgets_values_named']['clip_name'],'synthetic-clip.safetensors')
        self.assertEqual(by_id[44]['widgets_values_named']['unet_name'],'selected.safetensors')
        self.assertEqual(by_id[19]['widgets_values_named']['seed'],123)

    def test_invalid_json_or_api_format_is_rejected(self):
        self.path.parent.mkdir()
        for content in ('not json','[]','{"1":{"class_type":"KSampler"}}'):
            self.path.write_text(content,encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'workflows/README.md'):
                builders.load_anima_template(self.path)

    def test_model_listing_without_local_workflow_does_not_crash(self):
        runtime=SimpleNamespace(comfy_url='http://local',checkpoint_families={})
        with patch('comfyui_wrapper.models.model_catalog.BASE',self.root),patch('urllib.request.urlopen',side_effect=OSError('offline')):
            result=ModelCatalog(runtime).checkpoints('anima')
        self.assertEqual(result['names'],[])
        self.assertIn('anima_template.json',result['warning'])

    def test_prompt_only_preflight_requires_user_workflow_without_network(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('no network')):
            result=preflight.check({'target':'anima','execute':False},{},self.path,[])
        self.assertFalse(result['ok'])
        self.assertIn('workflows/README.md',result['checks'][-1]['detail'])

    def test_missing_workflow_is_rejected_before_analysis(self):
        app=create_app(self.root/'results')
        with patch('comfyui_wrapper.routes.jobs.BASE',self.root),patch('comfyui_wrapper.models.model_catalog.BASE',self.root),patch('comfyui_wrapper.analysis.generate.analyze') as analyze:
            response=app.test_client().post('/api/jobs',data=dict(target='anima',checkpoint='chosen.safetensors',instruction='scene'),headers={'X-Requested-With':'LLMPC'})
        self.assertEqual(response.status_code,400)
        self.assertIn('workflows/README.md',response.json['error'])
        analyze.assert_not_called()
