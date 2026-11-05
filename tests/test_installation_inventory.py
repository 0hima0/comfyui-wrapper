"""Read-only inventory and update checks use mocked servers, never local settings."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from comfyui_wrapper.system.installation import inventory, check_update, stable_version
from comfyui_wrapper.integrations.comfy_client import ComfyError


class InstallationTests(unittest.TestCase):
    def update(self, current, tag):
        release=io.BytesIO(json.dumps(dict(tag_name=tag,prerelease=False,draft=False)).encode())
        with patch('comfyui_wrapper.system.installation.comfy_client.api',return_value={'system':{'comfyui_version':current}}), patch('comfyui_wrapper.system.installation.urllib.request.urlopen',return_value=release):
            return check_update('http://localhost:8188')

    def test_stable_release_comparison(self):
        self.assertEqual(self.update('0.9.0','v0.10.0')['state'],'update_available')
        self.assertEqual(self.update('0.10.0','v0.10.0')['state'],'up_to_date')
        self.assertEqual(self.update('0.11.0','v0.10.0')['state'],'ahead')

    def test_development_and_missing_versions_are_unknown(self):
        for current in ('0.10.0-dev',None,'unknown'):
            with self.subTest(current=current):
                self.assertEqual(self.update(current,'v0.10.0')['state'],'unknown')
        self.assertIsNone(stable_version('0.10.0-rc1'))

    def test_network_failure_does_not_claim_up_to_date(self):
        with patch('comfyui_wrapper.system.installation.comfy_client.api',side_effect=ComfyError('offline')), patch('comfyui_wrapper.system.installation.urllib.request.urlopen',side_effect=OSError('offline')):
            result=check_update('http://localhost:8188')
        self.assertEqual(result['state'],'unknown')
        self.assertEqual(len(result['warnings']),2)

    def test_inventory_uses_comfyui_only_without_fallback_models(self):
        catalog=Mock()
        catalog.checkpoints.side_effect=[dict(source='fallback',names=['missing'],warning='offline'),dict(source='comfyui',names=['model.safetensors'])]
        catalog.classify.return_value=dict(family='sdxl',family_label='SDXL')
        services=SimpleNamespace(catalog=catalog,runtime=SimpleNamespace(comfy_url='http://localhost:8188',lora_folders={}))
        response={'LoraLoader':{'input':{'required':{'lora_name':[['sdxl/example.safetensors']]}}}}
        with patch('comfyui_wrapper.system.installation.comfy_client.api',return_value=response):
            result=inventory(services)
        self.assertEqual({row['name'] for row in result['items']},{'model.safetensors','sdxl/example.safetensors'})
        self.assertTrue(result['warnings'])

    def test_failed_lora_lookup_preserves_model_results(self):
        catalog=Mock()
        catalog.checkpoints.return_value=dict(source='comfyui',names=['model.safetensors'])
        catalog.classify.return_value=dict(family='sdxl',family_label='SDXL')
        services=SimpleNamespace(catalog=catalog,runtime=SimpleNamespace(comfy_url='http://localhost:8188',lora_folders={}))
        with patch('comfyui_wrapper.system.installation.comfy_client.api',side_effect=ComfyError('offline')):
            result=inventory(services)
        self.assertEqual(len(result['items']),1)
        self.assertTrue(result['warnings'])