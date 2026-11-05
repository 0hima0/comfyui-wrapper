"""Independent named instruction storage, using synthetic data only."""
import tempfile
import unittest
from pathlib import Path
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.settings.instruction_presets import InstructionStore

class InstructionPresetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=create_app(self.root);self.client=self.app.test_client();self.headers={'X-Requested-With':'LLMPC'}

    def test_named_instruction_crud_survives_restart_and_preserves_text(self):
        text='画像1と画像2の人物が座る。\n文字は含めない。'
        response=self.client.post('/api/instruction-presets',json=dict(name=' 公園 ',instruction=text),headers=self.headers)
        self.assertEqual(response.status_code,200);key=response.json['id']
        self.assertEqual(response.json['items'][0]['name'],'公園')
        fresh=InstructionStore(self.root/'instruction-presets.sqlite3');self.assertEqual(fresh.all()[0]['instruction'],text)
        response=self.client.put('/api/instruction-presets/'+key,json=dict(name='ベンチ',instruction='並んで座る'),headers=self.headers)
        self.assertEqual(response.json['items'][0]['name'],'ベンチ')
        self.assertEqual(self.client.delete('/api/instruction-presets/'+key,headers=self.headers).json['items'],[])
        self.assertEqual(self.client.get('/api/history').json['items'],[])

    def test_invalid_duplicate_missing_and_access_guards(self):
        data=dict(name='名前',instruction='場面')
        self.assertEqual(self.client.post('/api/instruction-presets',json=data).status_code,403)
        self.client.post('/api/instruction-presets',json=data,headers=self.headers)
        self.assertEqual(self.client.post('/api/instruction-presets',json=data,headers=self.headers).status_code,400)
        for bad in [None,dict(name='',instruction='x'),dict(name='x'*81,instruction='x'),dict(name='x',instruction=' '),dict(name='x',instruction='x'*8001),dict(name='a\nb',instruction='x')]:
            self.assertEqual(self.client.post('/api/instruction-presets',json=bad,headers=self.headers).status_code,400)
        self.assertEqual(self.client.put('/api/instruction-presets/missing',json=data,headers=self.headers).status_code,404)
        self.assertEqual(len(self.client.get('/api/instruction-presets').json['items']),1)
