from comfyui_wrapper.workflows import builders
from tests.support import wait_for_completion, image_upload
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from comfyui_wrapper.webui import create_app


class WebUITests(unittest.TestCase):
    def setUp(self):
        self.socket_patch=patch('comfyui_wrapper.integrations.comfy_progress.open_socket',return_value=None)
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.app = create_app(Path(self.temp.name) / 'results')
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def form(self, **values):
        return dict(image=image_upload(filename='../../reference.png'), instruction='服を青に', **values)

    def submit(self, **values):
        return self.client.post('/api/jobs', data=self.form(**values),
                                headers={'X-Requested-With': 'LLMPC'})

    def wait(self, job):
        return wait_for_completion(self.client,'/api/jobs/'+job,self.app)

    def test_home(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('画像・要望', response.get_data(as_text=True))
        self.assertNotIn('id="analysis-model"',response.get_data(as_text=True))

    def test_rating_is_applied_to_workflow_and_report(self):
        result=dict(summary_ja='青',positive='nsfw, blue dress',negative='safe, blurry',uncertainties_ja='不明')
        with patch('comfyui_wrapper.analysis.generate.analyze',return_value=result):
            response=self.submit(rating='safe')
            data=self.wait(response.json['job_id'])
        self.assertEqual(data['result']['positive'],'safe, blue dress')
        self.assertEqual(data['result']['negative'],'blurry')
        response=self.client.get(data['downloads']['analysis.json'])
        self.assertEqual(response.json['rating']['resolved'],'safe')
        response.close()
        response=self.client.get(data['downloads']['workflow.json'])
        node=next(n for n in response.json['nodes'] if n['id']==11)
        self.assertEqual(node['widgets_values'],['safe, blue dress'])
        response.close()
        self.assertEqual(self.submit(rating='auto').status_code,400)
        self.assertEqual(self.submit(rating='invalid').status_code,400)

    def test_models_are_loaded_from_comfy(self):
        def info(url,timeout):
            kind,field=('UNETLoader','unet_name') if url.endswith('UNETLoader') else ('CheckpointLoaderSimple','ckpt_name')
            return io.BytesIO(json.dumps({kind:{'input':{'required':{field:[['installed.safetensors']]}}}}).encode())
        with patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',side_effect=info):
            data=self.client.get('/api/models').json
        self.assertEqual([(m['target'],m['name']) for m in data['models']],
                         [('anima','installed.safetensors'),('animagine','installed.safetensors')])
        with patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',side_effect=OSError('offline')):
            self.assertEqual(self.client.get('/api/models').json['models'],[])

    def test_execute_end_to_end_with_mock_comfy_server(self):
        from comfyui_wrapper.integrations import comfy_client
        from comfyui_wrapper.analysis import generate
        self.app=create_app(Path(self.temp.name)/'wd-png-results',wd_dir=Path(self.temp.name))
        self.client=self.app.test_client()
        result=dict(summary_ja='青い服',positive='blue dress',negative='blurry',uncertainties_ja='不明')
        workflow=comfy_client.prepare(builders.animagine_workflow(result,1024,1024,1,'installed.safetensors'))
        graph=comfy_client.to_api(workflow)
        info={n['class_type']:{'input':{'required':{k:['ANY'] for k in n['inputs']}}} for n in graph.values()}
        info['CheckpointLoaderSimple']['input']['required']['ckpt_name']=[['installed.safetensors']]
        png=io.BytesIO()
        Image.new('RGB',(32,32),'blue').save(png,'PNG')
        submitted=[]
        def server(req,timeout=30):
            url=req if isinstance(req,str) else req.full_url
            if '/object_info/CheckpointLoaderSimple' in url:
                reply={'CheckpointLoaderSimple':info['CheckpointLoaderSimple']}
            elif url.endswith('/object_info'): reply=info
            elif url.endswith('/prompt'):
                submitted.append(json.loads(req.data))
                reply={'prompt_id':'p1','node_errors':{}}
            elif '/history/p1' in url:
                reply={'p1':{'status':{'completed':True,'status_str':'success'},'outputs':{'7':{
                    'images':[{'filename':'generated.png','subfolder':'','type':'output'}]}}}}
            elif '/view?' in url: return io.BytesIO(png.getvalue())
            else: raise AssertionError(url)
            return io.BytesIO(json.dumps(reply).encode())
        reference_predictions=[{'tag':'red_dress','category':0,'score':.8}]
        output_predictions=[{'tag':'blue_dress','category':0,'score':.92}]
        with patch('urllib.request.urlopen',side_effect=server),patch('comfyui_wrapper.analysis.generate.analyze',return_value=result) as analyze, \
                patch('comfyui_wrapper.analysis.wd_tagger.wd_tags',side_effect=[('red_dress',reference_predictions),('blue_dress',output_predictions)]) as wd:
            response=self.submit(target='animagine',checkpoint='installed.safetensors',execute='on',use_wd='on',threshold='0.5',
                                 additional_positive=' blue dress, cinematic lighting ',additional_negative=' watermark ',
                                 analysis_model='vision-selected:8b')
            self.assertEqual(response.status_code,202)
            data=self.wait(response.json['job_id'])
        self.assertEqual(data['state'],'done')
        self.assertEqual(data['progress']['stage'],'done')
        self.assertEqual(data['prompt_id'],'p1')
        self.assertEqual(data['images'],['image_0.png'])
        self.assertEqual(data['output_files'],[{'webui_filename':'image_0.png','comfy_filename':'generated.png',
            'comfy_subfolder':'','comfy_type':'output'}])
        record=self.client.get('/api/history/'+response.json['job_id']).json
        self.assertEqual(record['output_files'],data['output_files'])
        self.assertEqual(len(submitted),1)
        self.assertEqual(analyze.call_args.args[4],'qwen3-vl:8b-instruct')
        self.assertEqual(analyze.call_args.args[2],'')
        self.assertEqual(analyze.call_args.kwargs['ui_positive'],'blue dress, cinematic lighting')
        self.assertEqual(data['result']['positive'],'blue dress, cinematic lighting')
        self.assertEqual(data['result']['negative'],'blurry, watermark')
        encodes=[n['inputs']['text'] for n in submitted[0]['prompt'].values() if n['class_type']=='CLIPTextEncode']
        self.assertEqual(encodes,['blue dress, cinematic lighting','blurry, watermark'])
        image=self.client.get(data['downloads']['image_0.png']+'?inline=1')
        self.assertTrue(image.data.startswith(b'\x89PNG'))
        with Image.open(io.BytesIO(image.data)) as saved:
            metadata=json.loads(saved.text['llmpc'])
            self.assertEqual(metadata['analysis']['wd_threshold'],.5)
            self.assertEqual(metadata['analysis']['additional_prompts'],{'positive':'blue dress, cinematic lighting','negative':'watermark'})
            self.assertEqual(metadata['analysis']['model'],'qwen3-vl:8b-instruct')
            self.assertEqual(metadata['analysis']['prompt_conflicts']['removed_wd_tags'][0]['tag'],'red_dress')
            self.assertEqual(metadata['analysis']['analysis_prompts']['positive'],'blue dress')
            self.assertEqual(metadata['analysis']['result']['positive'],'blue dress, cinematic lighting')
            self.assertEqual(metadata['analysis']['wd_predictions'],reference_predictions)
            self.assertEqual(metadata['generated_image_wd']['threshold'],.5)
            self.assertEqual(metadata['generated_image_wd']['predictions'],output_predictions)
            self.assertEqual(metadata['generated_image_wd']['source'],'generated_image')
            self.assertEqual(metadata['analysis']['prompt_id'],'p1')
            self.assertEqual(json.loads(saved.text['prompt']),submitted[0]['prompt'])
            self.assertIn('nodes',json.loads(saved.text['workflow']))
        self.assertEqual(wd.call_count,2)
        self.assertEqual(wd.call_args.args[2],.5)
        self.assertEqual(submitted[0]['extra_data']['extra_pnginfo']['llmpc']['analysis']['wd_threshold'],.5)
        image.close()
        archive=self.client.get(data['downloads']['results.zip'])
        with zipfile.ZipFile(io.BytesIO(archive.data)) as zipped:
            self.assertIn('image_0.png',zipped.namelist())
            self.assertIn('workflow_api.json',zipped.namelist())
            with Image.open(io.BytesIO(zipped.read('image_0.png'))) as saved:
                self.assertEqual(json.loads(saved.text['llmpc'])['generated_image_wd']['tags'],'blue_dress')
            self.assertEqual(zipped.read('positive.txt').decode(),'blue dress, cinematic lighting')
            self.assertEqual(zipped.read('negative.txt').decode(),'blurry, watermark')
        archive.close()

    def test_execute_requires_installed_model(self):
        with patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',side_effect=OSError('offline')):
            self.assertEqual(self.submit(execute='on').status_code,400)

    def test_png_metadata_when_wd_disabled_or_output_tagging_fails(self):
        result=dict(summary_ja='青',positive='blue',negative='blurry',uncertainties_ja='不明')
        info={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['installed.safetensors']]}}}}
        png=io.BytesIO()
        Image.new('RGB',(8,8),'blue').save(png,'PNG')
        for enabled in (False,True):
            self.app=create_app(Path(self.temp.name)/str(enabled),wd_dir=Path(self.temp.name))
            self.client=self.app.test_client()
            with self.subTest(enabled=enabled), patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(info).encode())), \
                    patch('comfyui_wrapper.analysis.generate.analyze',return_value=result), \
                    patch('comfyui_wrapper.integrations.comfy_client.execute',return_value=[{'filename':'x.png'}]), \
                    patch('comfyui_wrapper.integrations.comfy_client.fetch_image',return_value=png.getvalue()), \
                    patch('comfyui_wrapper.analysis.wd_tagger.wd_tags',side_effect=[('reference',[]),RuntimeError('tagging failed')]) as wd:
                if enabled:
                    with self.assertLogs(self.app.logger,level='ERROR'):
                        response=self.submit(target='animagine',checkpoint='installed.safetensors',execute='on',use_wd='on')
                        data=self.wait(response.json['job_id'])
                else:
                    response=self.submit(target='animagine',checkpoint='installed.safetensors',execute='on')
                    data=self.wait(response.json['job_id'])
                self.assertEqual(data['state'],'done')
                response=self.client.get(data['downloads']['image_0.png'])
                with Image.open(io.BytesIO(response.data)) as image:
                    meta=json.loads(image.text['llmpc'])
                    self.assertEqual(meta['generated_image_wd']['status'],'error' if enabled else 'disabled')
                    self.assertEqual(meta['analysis']['wd_threshold'],.35 if enabled else None)
                response.close()
                self.assertEqual(wd.call_count,2 if enabled else 0)

    def test_comfy_failure_preserves_generated_prompts(self):
        from comfyui_wrapper.integrations import comfy_client
        result=dict(summary_ja='青い服',positive='blue dress',negative='blurry',uncertainties_ja='不明')
        info={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['installed.safetensors']]}}}}
        def execute(url,graph,workflow,submitted,status,**kwargs):
            submitted('p-failed')
            raise comfy_client.ComfyError('ComfyUIで画像生成に失敗しました: OOM')
        with patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(info).encode())), \
                patch('comfyui_wrapper.analysis.generate.analyze',return_value=result),patch('comfyui_wrapper.integrations.comfy_client.execute',side_effect=execute):
            with self.assertLogs(self.app.logger,level='ERROR'):
                response=self.submit(target='animagine',checkpoint='installed.safetensors',execute='on')
                data=self.wait(response.json['job_id'])
        self.assertEqual(data['state'],'error')
        self.assertEqual(data['prompt_id'],'p-failed')
        self.assertIn('OOM',data['message'])
        response=self.client.get(data['downloads']['positive.txt'])
        self.assertEqual(response.data.decode(),'blue dress')
        response.close()

    def test_checkpoint_list_for_each_loader(self):
        for target, kind, field in [('anima','UNETLoader','unet_name'),
                                    ('animagine','CheckpointLoaderSimple','ckpt_name')]:
            info = {kind:{'input':{'required':{field:[['folder/model-b.safetensors','model-a.safetensors']]}}}}
            with self.subTest(target=target), patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',
                    return_value=io.BytesIO(json.dumps(info).encode())) as call:
                response = self.client.get('/api/checkpoints?target='+target)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json['names'],['folder/model-b.safetensors','model-a.safetensors'])
                self.assertEqual(response.json['source'],'comfyui')
                self.assertTrue(call.call_args.args[0].endswith('/object_info/'+kind))

    def test_checkpoint_fallback_and_empty_list(self):
        with patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',side_effect=OSError('offline')):
            data = self.client.get('/api/checkpoints?target=anima').json
            self.assertEqual(data['names'],['anima-base-v1.0.safetensors'])
            self.assertEqual(data['source'],'fallback')
            self.assertTrue(data['warning'])
        info = {'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[[]]}}}}
        with patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(info).encode())):
            data = self.client.get('/api/checkpoints?target=animagine').json
            self.assertEqual(data['names'],[])
            self.assertTrue(data['warning'])
        self.assertEqual(self.client.get('/api/checkpoints?target=unknown').status_code,400)

    def test_wd_optional_and_selected_checkpoint_saved(self):
        self.app = create_app(Path(self.temp.name)/'wd-results', wd_dir=Path(self.temp.name))
        self.client = self.app.test_client()
        result = dict(summary_ja='青い服',positive='blue dress',negative='blurry',uncertainties_ja='不明')
        for target, enabled in [('anima',False),('animagine',True)]:
            with self.subTest(target=target), patch('comfyui_wrapper.analysis.generate.analyze',return_value=result) as analyze, \
                    patch('comfyui_wrapper.analysis.wd_tagger.wd_tags',return_value=('blue_dress',[])) as tagger:
                response = self.submit(target=target,use_wd='on' if enabled else '',
                                       checkpoint='folder/custom.safetensors')
                data = self.wait(response.json['job_id'])
                self.assertEqual(data['state'],'done')
                self.assertEqual(tagger.call_count,1 if enabled else 0)
                self.assertEqual(analyze.call_args.args[2],'blue_dress' if enabled else '')
                download = self.client.get(data['downloads']['workflow.json'])
                nodes = download.json['nodes']
                loader = next(n for n in nodes if n['type'] == ('UNETLoader' if target=='anima' else 'CheckpointLoaderSimple'))
                self.assertEqual(loader['widgets_values'][0],'folder/custom.safetensors')
                key = 'unet_name' if target=='anima' else 'ckpt_name'
                self.assertEqual(loader['widgets_values_named'][key],'folder/custom.safetensors')
                download.close()
                report = self.client.get(data['downloads']['analysis.json'])
                self.assertEqual(report.json['use_wd'],enabled)
                self.assertEqual(report.json['checkpoint'],'folder/custom.safetensors')
                report.close()

    def test_upload_generate_download_both_models(self):
        result = dict(summary_ja='青い服', positive='blue dress', negative='blurry', uncertainties_ja='不明')
        for target in ('anima', 'animagine'):
            with self.subTest(target=target), patch('comfyui_wrapper.analysis.generate.analyze', return_value=result) as analyze:
                response = self.submit(target=target, seed='123')
                self.assertEqual(response.status_code, 202)
                data = self.wait(response.json['job_id'])
                self.assertEqual(data['state'], 'done')
                self.assertEqual(analyze.call_args.args[1], '服を青に')
                download = self.client.get(data['downloads']['workflow.json'])
                workflow = download.json
                self.assertIn('nodes', workflow)
                download.close()
                zipped = self.client.get(data['downloads']['results.zip'])
                with zipfile.ZipFile(io.BytesIO(zipped.data)) as archive:
                    self.assertEqual(set(archive.namelist()), {'workflow.json', 'analysis.json', 'positive.txt', 'negative.txt'})
                zipped.close()
                self.assertFalse((Path(self.temp.name) / 'reference.png').exists())

    def test_invalid_inputs_and_origin(self):
        for values in (dict(width='513'), dict(seed='-1'), dict(target='unknown'),
                       dict(threshold='nan'), dict(use_wd='on')):
            with self.subTest(values=values):
                self.assertEqual(self.submit(**values).status_code, 400)
        self.assertEqual(self.submit(execute='on',additional_positive='x'*8001).status_code,400)
        self.assertEqual(self.submit(restored_generation='{"steps":-2}').status_code,400)
        self.assertEqual(self.submit(restored_generation='{"extra_node":"bad"}').status_code,400)
        self.assertEqual(self.client.post('/api/jobs', data=self.form()).status_code, 403)
        self.assertEqual(self.client.post('/api/jobs', data=self.form(), headers={
            'X-Requested-With':'LLMPC','Origin':'https://other.example'}).status_code, 403)

    def test_invalid_image_and_upload_limit(self):
        response = self.client.post('/api/jobs', data={'image':(io.BytesIO(b'not image'),'a.png')},
                                    headers={'X-Requested-With':'LLMPC'})
        self.assertEqual(response.status_code, 400)
        self.app.config['MAX_CONTENT_LENGTH'] = 100
        self.assertEqual(self.submit().status_code, 413)

    def test_busy(self):
        lock = self.app.extensions['generation_lock']
        lock.acquire()
        try:
            self.assertEqual(self.submit().status_code, 409)
        finally:
            lock.release()

    def test_additional_prompts_used_when_exporting_without_execution(self):
        result=dict(summary_ja='青',positive='blue',negative='blurry',uncertainties_ja='不明')
        with patch('comfyui_wrapper.analysis.generate.analyze',return_value=result):
            response=self.submit(additional_positive='extra',additional_negative='extra')
            data=self.wait(response.json['job_id'])
        self.assertEqual(data['result'],dict(result,positive='blue, extra',negative='blurry, extra'))
        response=self.client.get(data['downloads']['analysis.json'])
        self.assertEqual(response.json['additional_prompts'],{'positive':'extra','negative':'extra'})
        response.close()

    def test_failure_releases_worker_and_hides_downloads(self):
        with self.assertLogs(self.app.logger,level='ERROR'), patch('comfyui_wrapper.analysis.generate.analyze', side_effect=RuntimeError('mock failure')):
            response = self.submit()
            job = response.json['job_id']
            self.assertEqual(self.wait(job)['state'], 'error')
        self.assertEqual(self.client.get(f'/download/{job}/workflow.json').status_code,404)
        lock = self.app.extensions['generation_lock']
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()

    def test_unknown_download(self):
        self.assertEqual(self.client.get('/download/'+'a'*32+'/workflow.json').status_code,404)
        self.assertEqual(self.client.get('/download/'+'a'*32+'/generate.py').status_code,404)


if __name__ == '__main__':
    unittest.main()
