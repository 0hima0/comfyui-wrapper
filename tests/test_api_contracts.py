"""Compatibility and request guards across all feature route modules."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from comfyui_wrapper.webui import create_app


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.app=create_app(Path(self.temp.name))
        self.client=self.app.test_client()

    def test_public_routes_keep_their_methods_paths_and_endpoint_names(self):
        expected=json.loads((Path(__file__).parent/'fixtures/routes.json').read_text(encoding='utf-8'))
        actual=sorted([dict(rule=rule.rule,endpoint=rule.endpoint,methods=sorted(rule.methods))
                       for rule in self.app.url_map.iter_rules()],key=lambda row:(row['rule'],row['endpoint']))
        self.assertEqual(actual,expected)

    def test_every_write_route_keeps_custom_header_and_origin_guards(self):
        import re
        for rule in self.app.url_map.iter_rules():
            path=re.sub(r'<[^>]+>','a'*32,rule.rule)
            for method in rule.methods & {'POST','PUT','DELETE'}:
                with self.subTest(path=path,method=method):
                    self.assertEqual(self.client.open(path,method=method).status_code,403)
                    response=self.client.open(path,method=method,headers={
                        'X-Requested-With':'LLMPC','Origin':'https://unrelated.example'})
                    self.assertEqual(response.status_code,403)

    def test_lora_options_distinguish_empty_catalog_from_upstream_failure(self):
        from comfyui_wrapper.integrations.comfy_client import ComfyError
        for names in ([], ['sdxl/example.safetensors']):
            with patch('comfyui_wrapper.integrations.comfy_client.api', return_value={
                    'LoraLoader': {'input': {'required': {'lora_name': [names]}}}}):
                data = self.client.get('/api/generation-options').json
            self.assertTrue(data['loras_available'])
            self.assertEqual(data['loras'], names)
        with patch('comfyui_wrapper.integrations.comfy_client.api', side_effect=ComfyError('offline')):
            data = self.client.get('/api/generation-options').json
        self.assertFalse(data['loras_available'])
        self.assertTrue(data['warnings'])
