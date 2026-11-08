"""Security boundary regression tests with synthetic inputs only."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import jsonify
from PIL import Image, UnidentifiedImageError
from werkzeug.datastructures import FileStorage
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.infrastructure.http_support import require_ui_request
from comfyui_wrapper.generation.reference_images import load_references, close_references
from comfyui_wrapper.settings.app_config import validate_trusted_hosts, load_config
from comfyui_wrapper.settings.config_editor import ConfigEditor


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name), trusted_hosts=['localhost', 'wrapper.test', '[::1]'])
        @self.app.post('/security-probe')
        def probe():
            require_ui_request()
            return jsonify(ok=True)
        self.client = self.app.test_client()

    def test_arbitrary_host_is_rejected_before_read_or_write(self):
        for method, url in [('get', '/'), ('post', '/security-probe')]:
            response = getattr(self.client, method)(url, base_url='http://attacker.test:7860',
                headers={'Origin':'http://attacker.test:7860', 'X-Requested-With':'LLMPC'})
            self.assertEqual(response.status_code, 400)

    def test_origin_requires_same_scheme_host_and_port(self):
        for origin, expected in [('http://wrapper.test:7860',200), ('https://wrapper.test:7860',403),
                                 ('http://wrapper.test:7861',403), ('null',403),
                                 ('http://wrapper.test:bad',403), ('http://[',403)]:
            with self.subTest(origin=origin):
                response=self.client.post('/security-probe', base_url='http://wrapper.test:7860',
                    headers={'Origin':origin, 'X-Requested-With':'LLMPC'})
                self.assertEqual(response.status_code, expected)
        self.assertEqual(self.client.get('/',base_url='http://[::1]:7860').status_code,200)

    def test_host_configuration_rejects_wildcards_and_urls(self):
        for value in [[], ['.example.com'], ['*'], ['0.0.0.0'], ['http://localhost'], ['localhost:7860'], ['[::]']]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_trusted_hosts(value)

    def test_disallowed_image_plugin_is_never_called(self):
        Image.init()
        with patch.dict(Image.OPEN, {'EPS': (lambda *args: self.fail('EPS parser invoked'), lambda prefix: True)}):
            with self.assertRaises(UnidentifiedImageError):
                load_references([FileStorage(stream=io.BytesIO(b'%!PS-Adobe-3.0 EPSF-3.0\n'), filename='fake.png')])
            response=self.client.post('/api/lora-samples?name=synthetic',
                data={'images':(io.BytesIO(b'%!PS-Adobe-3.0 EPSF-3.0\n'),'fake.png')},
                headers={'X-Requested-With':'LLMPC'})
            self.assertEqual(response.status_code,400)

    def test_old_configuration_defaults_and_host_setting_round_trip(self):
        path=Path(self.temp.name)/'synthetic-settings.json'
        path.write_text('{}',encoding='utf-8')
        self.assertIn('localhost',load_config(path)['trusted_hosts'])
        editor=ConfigEditor(path)
        current=editor.read()
        candidate=current['settings']
        candidate['trusted_hosts']=['localhost','wrapper.test']
        review=editor.review(candidate,current['revision'])
        editor.save(candidate,current['revision'],review['confirmation'])
        self.assertEqual(load_config(path)['trusted_hosts'],['localhost','wrapper.test'])

    def test_supported_reference_formats_remain_usable(self):
        for fmt in ('PNG','JPEG','WEBP'):
            with self.subTest(fmt=fmt):
                raw=io.BytesIO()
                with Image.new('RGB',(2,2),'blue') as image:
                    image.save(raw,format=fmt)
                raw.seek(0)
                refs=load_references([FileStorage(stream=raw,filename='synthetic.'+fmt.lower())])
                try:self.assertEqual(refs[0].image.size,(2,2))
                finally:close_references(refs)
