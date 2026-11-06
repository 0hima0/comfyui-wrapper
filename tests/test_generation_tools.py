from tests.support import wait_for_completion, image_upload
import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.system import preflight
from comfyui_wrapper.generation.generation_pipeline import build_workflow
from comfyui_wrapper.settings.settings_presets import PresetStore
from comfyui_wrapper.webui import create_app, BASE


class GenerationToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=create_app(self.root)
        self.client=self.app.test_client()
        self.headers={'X-Requested-With':'LLMPC'}

    def form(self,color='blue',**values):
        values.setdefault('target','animagine')
        return dict(image=image_upload(color,size=(24,32),mode='RGBA'),instruction='公園で座る',**values)

    def wait(self,job):
        return wait_for_completion(self.client,'/api/jobs/'+job,self.app)

    def original(self,**extra):
        with patch('comfyui_wrapper.analysis.generate.analyze',return_value=dict(positive='blue dress',negative='text',summary_ja='青',uncertainties_ja='')):
            response=self.client.post('/api/jobs',data=self.form(**extra),headers=self.headers)
            self.assertEqual(response.status_code,202,response.json)
            record=self.wait(response.json['job_id']);self.assertEqual(record['state'],'done',record)
        return response.json['job_id'],record

    def test_reuse_skips_ollama_and_writes_edited_prompts_and_new_settings(self):
        job,_=self.original()
        with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=AssertionError('must not analyze')) as analyze:
            response=self.client.post('/api/jobs',data=self.form(reuse_job_id=job,final_positive='two people, sunset',final_negative='logo',seed='123',width='1152',steps='35'),headers=self.headers)
            self.assertEqual(response.status_code,202,response.json)
            record=self.wait(response.json['job_id']);self.assertEqual(record['state'],'done',record)
            analyze.assert_not_called()
        new=response.json['job_id'];report=json.loads((self.root/new/'analysis.json').read_text(encoding='utf-8'))
        self.assertEqual(report['analysis_execution'],dict(mode='reused',source_job_id=job))
        self.assertEqual(report['result']['positive'],'two people, sunset')
        self.assertEqual(record['settings']['seed'],123)
        workflow=json.loads((self.root/new/'workflow.json').read_text(encoding='utf-8'))
        sampler=next(n for n in workflow['nodes'] if n['type']=='KSampler')
        self.assertEqual(sampler['widgets_values_named']['steps'],35)
        self.assertIn('two people, sunset',[n.get('widgets_values_named',{}).get('text') for n in workflow['nodes']])

    def test_reuse_rejects_changed_images_instruction_and_old_or_deleted_sources(self):
        job,_=self.original()
        for change in ({'color':'red'},{'rating':'safe'}):
            form=self.form(reuse_job_id=job,final_positive='scene',final_negative='',**change)
            response=self.client.post('/api/jobs',data=form,headers=self.headers)
            self.assertEqual(response.status_code,400,response.json)
            self.assertFalse(self.app.extensions['generation_lock'].locked())
        form=self.form(reuse_job_id=job,final_positive='scene',final_negative='');form['instruction']='海辺'
        self.assertEqual(self.client.post('/api/jobs',data=form,headers=self.headers).status_code,400)
        report_path=self.root/job/'analysis.json';report=json.loads(report_path.read_text(encoding='utf-8'));report.pop('reuse_version');report_path.write_text(json.dumps(report),encoding='utf-8')
        self.assertEqual(self.client.post('/api/jobs',data=self.form(reuse_job_id=job,final_positive='scene',final_negative=''),headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/jobs',data=self.form(reuse_job_id='../bad',final_positive='scene',final_negative=''),headers=self.headers).status_code,400)

    def test_reuse_keeps_regional_people_and_updates_lora_strength(self):
        loras=[dict(name='sdxl/person.safetensors',strength_model=.7,strength_clip=.6,trigger='person',scope='image:1')]
        def form(**extra):
            value=self.form(target='animagine',checkpoint='animagine-xl-4.0-opt.safetensors',preserve_people='on',loras=json.dumps(loras),**extra)
            value['image']=[value['image'],self.form(color='red')['image']]
            return value
        with patch('comfyui_wrapper.analysis.generate.analyze',return_value=dict(positive='blue dress',negative='text',summary_ja='二人',uncertainties_ja='')):
            response=self.client.post('/api/jobs',data=form(),headers=self.headers);job=response.json['job_id'];self.assertEqual(self.wait(job)['state'],'done')
        loras[0]['strength_model']=.25;loras[0]['strength_clip']=.35
        with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=AssertionError('must not analyze')):
            response=self.client.post('/api/jobs',data=form(reuse_job_id=job,final_positive='two people at sunset',final_negative='text'),headers=self.headers)
            self.assertEqual(response.status_code,202,response.json);new=response.json['job_id'];self.assertEqual(self.wait(new)['state'],'done')
        workflow=json.loads((self.root/new/'workflow.json').read_text(encoding='utf-8'))
        hooks=[n for n in workflow['nodes'] if n['type']=='CreateHookLora']
        self.assertEqual(hooks[0]['widgets_values_named']['strength_model'],.25)
        self.assertEqual(hooks[0]['widgets_values_named']['strength_clip'],.35)
        self.assertEqual(len([n for n in workflow['nodes'] if n['type']=='IPAdapterAdvanced']),2)

    def preset(self):
        return dict(name='横長',fields=dict(target='animagine',checkpoint='animagine-xl-4.0-opt.safetensors',width='1152',height='896',steps='35',cfg='5.5',seed='',execute=True,profile='auto'),loras=[])

    def test_presets_persist_update_delete_and_are_separate_from_results(self):
        data=self.preset();reply=self.client.post('/api/presets',json=data,headers=self.headers)
        self.assertEqual(reply.status_code,200,reply.json);preset_id=reply.json['id']
        restarted=create_app(self.root).test_client();self.assertEqual(restarted.get('/api/presets').json['items'][0]['fields']['cfg'],'5.5')
        data['name']='更新';data['fields']['cfg']='6'
        self.assertEqual(self.client.put('/api/presets/'+preset_id,json=data,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/gallery').json['items'],[])
        self.assertEqual(self.client.delete('/api/presets/'+preset_id,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/presets').json['items'],[])

    def test_presets_validation_and_origin_guards(self):
        self.assertEqual(self.client.post('/api/presets',json=self.preset()).status_code,403)
        self.assertEqual(self.client.post('/api/presets',json=self.preset(),headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        for values in ({'cfg':'nan'},{'width':'1000'},{'ollama_url':'http://evil'},{'execute':'true'},{'seed':'-1'}):
            data=self.preset();data['fields'].update(values)
            self.assertEqual(self.client.post('/api/presets',json=data,headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/presets',json=self.preset(),headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/presets',json=self.preset(),headers=self.headers).status_code,400)
        self.assertEqual(self.client.put('/api/presets/'+'f'*32,json=self.preset(),headers=self.headers).status_code,404)

    def test_preset_limit(self):
        store=PresetStore(self.root/'limit.sqlite3')
        for i in range(50):data=self.preset();data['name']=str(i);store.save(data)
        with self.assertRaises(ValueError):store.save(self.preset())
        first=store.all()[0];store.save(self.preset(),first['id'])
        self.assertEqual(len(store.all()),50)

    def preflight_settings(self):
        return dict(target='animagine',checkpoint='animagine-xl-4.0-opt.safetensors',execute=True,use_wd=False,preserve_people=False,
            analysis_model='qwen3-vl:8b-instruct',model_family={'family':'sdxl'},profile='animagine4',width=1024,height=1024,seed=0,
            loras=[],clip_skip=0,generation_effective=dict(steps=28,cfg=5,sampler_name='euler',scheduler='normal',denoise=1))

    def info(self,settings):
        workflow=build_workflow(dict(positive='scene',negative='text'),settings,BASE/'workflows/anima_template.json')
        return {n['class_type']:{'input':{'required':{key:['ANY'] for key in n['inputs']}}} for n in comfy_client.to_api(workflow).values()}

    def test_preflight_checks_model_nodes_and_choices_without_execution(self):
        settings=self.preflight_settings();info=self.info(settings)
        runtime=dict(comfy_url='http://local:8188',ollama_url='http://local:11434',ollama_urls=[],wd_dir=None)
        tags=lambda *a,**kw:io.BytesIO(json.dumps({'models':[{'name':'qwen3-vl:8b-instruct'}]}).encode())
        with patch('urllib.request.urlopen',side_effect=tags),patch('comfyui_wrapper.integrations.comfy_client.api',return_value=info),patch('comfyui_wrapper.integrations.comfy_client.execute') as execute:
            self.assertTrue(preflight.check(settings,runtime,BASE/'workflows/anima_template.json',[1])['ok']);execute.assert_not_called()
            del info['KSampler']
            result=preflight.check(settings,runtime,BASE/'workflows/anima_template.json',[1]);self.assertFalse(result['ok']);self.assertIn('KSampler',result['checks'][-1]['detail'])

    def test_preflight_handles_missing_ollama_model_and_reuse_without_ollama(self):
        settings=self.preflight_settings();settings['execute']=False
        runtime=dict(comfy_url='http://local',ollama_url='http://local',ollama_urls=[],wd_dir=None)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"models":[]}')):
            self.assertFalse(preflight.check(settings,runtime,BASE/'workflows/anima_template.json',[1])['ok'])
        with patch('urllib.request.urlopen',side_effect=AssertionError('no ollama')):
            self.assertTrue(preflight.check(settings,runtime,BASE/'workflows/anima_template.json',[1],True)['ok'])
        settings['use_wd']=True
        # Exporting reused prompts does not run WD again; generated images do.
        self.assertTrue(preflight.check(settings,runtime,BASE/'workflows/anima_template.json',[],True)['ok'])
        settings['execute']=True
        with patch('comfyui_wrapper.integrations.comfy_client.api',return_value=self.info(settings)):
            self.assertFalse(preflight.check(settings,runtime,BASE/'workflows/anima_template.json',[],True)['ok'])

    def test_preflight_endpoint_validates_settings_and_does_not_accept_runtime_urls(self):
        data=self.preset();data.pop('name');data['reference_ids']=[1]
        self.assertEqual(self.client.post('/api/preflight',json=data).status_code,403)
        with patch('comfyui_wrapper.system.preflight.check',return_value={'ok':True,'checks':[]}) as check:
            self.assertEqual(self.client.post('/api/preflight',json=data,headers=self.headers).status_code,200)
            self.assertEqual(check.call_args.args[1]['ollama_url'],'http://127.0.0.1:11434')
        data['fields']['comfy_url']='http://evil'
        self.assertEqual(self.client.post('/api/preflight',json=data,headers=self.headers).status_code,400)
