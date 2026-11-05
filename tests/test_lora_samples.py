import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from comfyui_wrapper.webui import create_app


class LoraSampleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name)
        self.client=create_app(self.root).test_client()
        self.headers={'X-Requested-With':'LLMPC'}

    def tearDown(self):self.temp.cleanup()

    def upload(self,name='sdxl/sample.safetensors',count=1,headers=None):
        files=[]
        for i in range(count):
            data=io.BytesIO();Image.new('RGB',(640,800),'blue').save(data,'PNG');data.seek(0);files.append((data,f'sample{i}.png'))
        return self.client.post('/api/lora-samples',data=dict(name=name,images=files),headers=headers or self.headers)

    def test_upload_view_restart_isolation_and_delete(self):
        result=self.upload(count=2)
        self.assertEqual(result.status_code,201,result.json)
        item=result.json['items'][0]
        original=self.client.get(item['image_url']);self.assertEqual(original.status_code,200);self.assertEqual(original.mimetype,'image/png');original.close()
        thumbnail=self.client.get(item['thumbnail_url']);self.assertEqual(thumbnail.status_code,200);self.assertIn('private',thumbnail.headers['Cache-Control']);thumbnail.close()
        fresh=create_app(self.root).test_client()
        self.assertEqual(len(fresh.get('/api/lora-samples?name=sdxl/sample.safetensors').json['items']),2)
        self.assertEqual(fresh.get('/api/lora-samples?name=sd15/sample.safetensors').json['items'],[])
        self.assertEqual(fresh.get('/api/lora-samples/names').json['names'],['sdxl/sample.safetensors'])
        result=fresh.delete('/api/lora-samples/'+item['id'],headers=self.headers)
        self.assertEqual(len(result.json['items']),1)
        self.assertEqual(fresh.get(item['image_url']).status_code,404)
        self.assertEqual(list((self.root/'.gallery-thumbnails').glob('*.jpg')),[])

    def test_limit_and_failed_batch_does_not_leave_files(self):
        self.assertEqual(self.upload(count=6).status_code,201)
        self.assertEqual(self.upload().status_code,400)
        self.assertEqual(len(list((self.root/'lora-samples').iterdir())),6)
        self.assertEqual(self.upload(name='sd15/other.safetensors').status_code,201)
        bad=self.client.post('/api/lora-samples',headers=self.headers,data=dict(name='bad',images=(io.BytesIO(b'<svg/>'),'fake.png')))
        self.assertEqual(bad.status_code,400)
        self.assertEqual(self.client.get('/api/lora-samples?name=bad').json['items'],[])

    def test_write_guards_and_large_upload(self):
        self.assertEqual(self.client.post('/api/lora-samples',data=dict(name='x')).status_code,403)
        self.assertEqual(self.upload(headers={**self.headers,'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.upload(name='').status_code,400)
        large=self.client.post('/api/lora-samples',headers=self.headers,data=dict(name='x',images=(io.BytesIO(b'x'*(5*1024*1024+1)),'big.png')))
        self.assertEqual(large.status_code,400)
        item=self.upload().json['items'][0]
        self.assertEqual(self.client.delete('/api/lora-samples/'+item['id']).status_code,403)

    def test_manager_scripts_are_self_contained_and_versioned(self):
        from html.parser import HTMLParser
        class Scripts(HTMLParser):
            def __init__(self):super().__init__();self.urls=[]
            def handle_starttag(self,tag,attrs):
                values=dict(attrs)
                if tag=='script' and 'src' in values:self.urls.append(values['src'])
        parser=Scripts();parser.feed(self.client.get('/loras').get_data(as_text=True))
        samples=next(url for url in parser.urls if '/lora_samples.js' in url)
        manager=next(url for url in parser.urls if '/lora_manager.js' in url)
        catalog=next(url for url in parser.urls if '/lora_catalog.js' in url)
        self.assertLess(parser.urls.index(samples),parser.urls.index(manager))
        self.assertLess(parser.urls.index(catalog),parser.urls.index(manager))
        self.assertIn('?v=',manager)
        for url in parser.urls:
            with self.client.get(url) as response:self.assertEqual(response.status_code,200,url)
        with self.client.get(samples) as response:
            source=response.get_data(as_text=True)
            self.assertIn('class LoraSamples',source)
            self.assertIn("$('managed-sample-files')?new LoraSamples()",source)

    def test_running_version_reports_sample_api_and_form(self):
        from comfyui_wrapper.webui import RELEASE, BASE
        response=self.client.get('/api/version')
        self.assertEqual(response.json['release'],RELEASE)
        self.assertEqual(response.json['app_directory'],str(BASE))
        self.assertTrue(response.json['lora_samples_api'])
        self.assertTrue(response.json['lora_samples_form'])
        self.assertEqual(response.headers['X-LLMPC-Version'],RELEASE)

    def test_static_asset_version_changes_after_file_update(self):
        from flask import url_for
        app=self.client.application
        assets=self.root/'assets';assets.mkdir();app.static_folder=str(assets)
        script=assets/'sample.js';script.write_text('initial',encoding='utf-8')
        with app.test_request_context():before=url_for('static',filename='sample.js')
        script.write_text('updated contents',encoding='utf-8')
        with app.test_request_context():after=url_for('static',filename='sample.js')
        self.assertNotEqual(before,after)

    def test_trigger_deletion_keeps_samples_and_manager_shows_sidebar(self):
        self.upload()
        self.client.put('/api/lora-triggers',headers=self.headers,json=dict(name='sdxl/sample.safetensors',trigger='sample'))
        self.client.delete('/api/lora-triggers',headers=self.headers,json=dict(name='sdxl/sample.safetensors'))
        self.assertEqual(len(self.client.get('/api/lora-samples?name=sdxl/sample.safetensors').json['items']),1)
        html=self.client.get('/loras').get_data(as_text=True)
        self.assertIn('data-sidebar-page="loras" title="LoRA管理" aria-current="page"',html)
        self.assertIn('managed-sample-files',html)


if __name__=='__main__':unittest.main()
