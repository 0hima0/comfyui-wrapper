from tests.support import wait_for_completion, image_upload
import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.gallery.history_store import HistoryStore
from comfyui_wrapper.generation.batch_generation import variants
from comfyui_wrapper.infrastructure import job_control


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name).resolve();self.app=create_app(self.root,wd_dir=self.root);self.client=self.app.test_client()
        self.headers={'X-Requested-With':'LLMPC'}
        self.png=io.BytesIO();Image.new('RGB',(8,8),'blue').save(self.png,'PNG')
        self.store=HistoryStore(self.root/'history.sqlite3')

    def tearDown(self):self.temp.cleanup()

    def form(self,count=3,field='strength_model'):
        return dict(image=(io.BytesIO(self.png.getvalue()),'reference.png'),execute='on',target='animagine',
                    checkpoint='animagine-xl-4.0-opt.safetensors',seed='42',
                    loras=json.dumps([dict(name='sdxl/test.safetensors',strength_model=.7,strength_clip=.6,trigger='person')]),
                    batch_plan=json.dumps(dict(count=count,ranges=[dict(field=field,lora=0,start=.3,end=.9)])))

    def mocks(self,execute=None,outputs=1):
        stack=ExitStack();self.addCleanup(stack.close)
        info={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['animagine-xl-4.0-opt.safetensors']]}}}}
        stack.enter_context(patch('comfyui_wrapper.models.model_catalog.urllib.request.urlopen',side_effect=lambda *a,**kw:io.BytesIO(json.dumps(info).encode())))
        stack.enter_context(patch('comfyui_wrapper.integrations.comfy_client.api',return_value={'LoraLoader':{'input':{'required':{'lora_name':[['sdxl/test.safetensors']]}}}}))
        analyze=stack.enter_context(patch('comfyui_wrapper.analysis.generate.analyze',return_value=dict(positive='blue',negative='text',summary_ja='青',uncertainties_ja='')))
        stack.enter_context(patch('comfyui_wrapper.integrations.comfy_client.execute',side_effect=execute,return_value=[dict(filename=f'result{i}.png') for i in range(outputs)]))
        stack.enter_context(patch('comfyui_wrapper.integrations.comfy_client.fetch_image',return_value=self.png.getvalue()))
        stack.enter_context(patch('comfyui_wrapper.analysis.wd_tagger.wd_tags',return_value=('blue',[])))
        return analyze

    def wait(self,batch_id):
        return wait_for_completion(self.client,'/api/batches/'+batch_id,self.app,timeout=6)

    def submit(self,**kw):
        response=self.client.post('/api/jobs',data=self.form(**kw),headers=self.headers)
        self.assertEqual(response.status_code,202,response.json)
        return response.json['batch_id']

    def test_matrix_runs_every_combination_and_keeps_review_metadata(self):
        self.mocks();form=self.form(count=4)
        form['batch_plan']=json.dumps(dict(mode='matrix',count=4,ranges=[dict(field='cfg',start=4,end=6,points=2),dict(field='strength_model',lora=0,start=.4,end=.8,points=2)]))
        response=self.client.post('/api/jobs',data=form,headers=self.headers);self.assertEqual(response.status_code,202,response.json)
        batch_id=response.json['batch_id'];batch=self.wait(batch_id);self.assertEqual(batch['completed'],4)
        records=[self.store.get(job) for job in batch['job_ids']]
        self.assertEqual([r['generation_settings']['cfg'] for r in records],[4,6,4,6])
        self.assertEqual([r['settings']['loras'][0]['strength_model'] for r in records],[.4,.4,.8,.8])
        self.assertEqual({item['batch_cell']['column'] for item in self.client.get('/api/gallery?batch_id='+batch_id).json['items']},{0,1})

    def test_set_name_validation_and_worker_snapshot(self):
        self.mocks();batch_id=self.submit();self.wait(batch_id)
        url='/api/batches/'+batch_id+'/name'
        self.assertEqual(self.client.put(url,json={'name':' 強度の比較 '},headers=self.headers).json['name'],'強度の比較')
        batches=self.app.extensions['app_services'].batches
        stale=batches.get(batch_id);stale.pop('name');batches.save(batch_id,stale)
        self.assertEqual(batches.get(batch_id)['name'],'強度の比較')
        self.assertIn('強度の比較',self.client.get('/batches').get_data(as_text=True))
        for bad in [None,42,'a'*81]:
            self.assertEqual(self.client.put(url,json={'name':bad},headers=self.headers).status_code,400)
        self.assertEqual(self.client.put(url,json={'name':''},headers=self.headers).json['name'],'')
        self.assertEqual(self.client.put('/api/batches/missing/name',json={'name':'x'},headers=self.headers).status_code,404)

    def test_isolation_plan_cached_analysis_and_selective_promotion(self):
        analyze=self.mocks();batch_id=self.submit();batch=self.wait(batch_id)
        self.assertEqual(batch['completed'],3);self.assertEqual(analyze.call_count,1)
        self.assertEqual(self.client.get('/api/gallery').json['items'],[])
        self.assertEqual(self.client.get('/api/history').json['items'],[])
        records=[self.store.get(k) for k in batch['job_ids']]
        self.assertEqual([r['settings']['loras'][0]['strength_model'] for r in records],[.3,.6,.9])
        strengths=[]
        for job in batch['job_ids']:
            workflow=json.loads((self.root/job/'workflow.json').read_text(encoding='utf-8'))
            node=next(n for n in workflow['nodes'] if n['type']=='LoraLoader')
            strengths.append(node['widgets_values'][1:3])
        self.assertEqual(strengths,[[.3,.6],[.6,.6],[.9,.6]])
        self.assertEqual({r['settings']['seed'] for r in records},{42})
        items=self.client.get('/api/gallery?batch_id='+batch_id).json['items'];self.assertEqual(len(items),3)
        self.assertEqual(self.client.put(items[0]['favorite_url'],json={'favorite':True},headers=self.headers).status_code,409)
        self.assertEqual(self.client.delete(items[0]['delete_url'],headers=self.headers).status_code,409)
        self.assertEqual(self.app.extensions['gallery_cleanup'].sweep(datetime(2030,1,1,tzinfo=timezone.utc)),0)
        kept=items[1];key=kept['job_id']+'/'+kept['filename']
        response=self.client.post('/api/batches/'+batch_id+'/finalize',json={'selected':[key]},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        normal=self.client.get('/api/gallery').json['items'];self.assertEqual([i['job_id'] for i in normal],[kept['job_id']])
        self.assertEqual(self.client.get('/batch/'+batch_id).status_code,404)
        self.assertEqual(self.client.get('/api/batches').json['items'],[])
        for item in items:
            if item['job_id']!=kept['job_id']:
                self.assertIsNone(self.store.get(item['job_id']));self.assertFalse((self.root/item['job_id']).exists())
        self.assertEqual(self.client.get(kept['settings_url']).status_code,200)

    def test_select_one_of_multiple_outputs_and_remove_other_from_zip(self):
        self.mocks(outputs=2);batch_id=self.submit(count=1);self.wait(batch_id)
        items=self.client.get('/api/gallery?batch_id='+batch_id).json['items'];kept=items[1]
        result=self.client.post('/api/batches/'+batch_id+'/finalize',json={'selected':[kept['job_id']+'/'+kept['filename']]},headers=self.headers)
        self.assertEqual(result.status_code,200,result.json)
        directory=self.root/kept['job_id'];self.assertFalse((directory/'image_0.png').exists())
        with zipfile.ZipFile(directory/'results.zip') as archive:
            self.assertNotIn('image_0.png',archive.namelist());self.assertIn('image_1.png',archive.namelist())
        report=json.loads((directory/'analysis.json').read_text(encoding='utf-8'))
        self.assertEqual(report['comfy_outputs'],[{'filename':'result1.png'}])
        self.assertEqual(self.store.get(kept['job_id'])['images'],['image_1.png'])

    def test_discard_all_and_guards(self):
        self.mocks();batch_id=self.submit(count=1);batch=self.wait(batch_id)
        url='/api/batches/'+batch_id+'/finalize'
        self.assertEqual(self.client.post(url,json={'selected':[]}).status_code,403)
        self.assertEqual(self.client.post(url,json={'selected':['../../x']},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post(url,json={'selected':[]},headers={**self.headers,'Origin':'http://other.test'}).status_code,403)
        self.assertEqual(self.client.post(url,json={'selected':[]},headers=self.headers).status_code,200)
        self.assertFalse((self.root/batch['job_ids'][0]).exists())
        self.assertEqual(self.client.post(url,json={'selected':[]},headers=self.headers).status_code,404)

    def test_cancel_retains_finished_images_for_review_and_blocks_early_finalize(self):
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set);calls=[]
        def execute(*a,**kw):
            calls.append(1)
            if len(calls)==2:
                entered.set();release.wait(3);job_control.check()
            return [dict(filename='x.png')]
        self.mocks(execute=execute);batch_id=self.submit()
        self.assertTrue(entered.wait(3))
        self.assertEqual(self.client.get('/api/generation-state').json,{'active_batch':batch_id})
        normal=self.form();normal.pop('batch_plan')
        rejected=self.client.post('/api/jobs',data=normal,headers=self.headers)
        self.assertEqual(rejected.status_code,409)
        self.assertEqual(self.client.post('/api/batches/'+batch_id+'/finalize',json={'selected':[]},headers=self.headers).status_code,409)
        self.client.post('/api/batches/'+batch_id+'/cancel',headers=self.headers);release.set()
        batch=self.wait(batch_id);self.assertEqual(batch['completed'],1);self.assertEqual(len(calls),2)
        self.assertEqual(self.client.get('/api/generation-state').json,{'active_batch':None})
        self.assertEqual(len(self.client.get('/api/gallery?batch_id='+batch_id).json['items']),1)

    def test_finalization_failure_preserves_review_and_restart_recovers_files(self):
        self.mocks();batch_id=self.submit(count=1);batch=self.wait(batch_id);job=batch['job_ids'][0]
        with patch('comfyui_wrapper.generation.batch_generation.zipfile.ZipFile',side_effect=OSError('mock disk full')):
            with self.assertLogs(self.app.logger,level='ERROR'):
                response=self.client.post('/api/batches/'+batch_id+'/finalize',json={'selected':[job+'/image_0.png']},headers=self.headers)
        self.assertEqual(response.status_code,500);self.assertTrue(self.store.get(job)['temporary'])
        originals=self.root/'.batch-finalize'/batch_id/'originals';originals.mkdir(parents=True)
        (self.root/job).rename(originals/job)
        (self.root/job).mkdir();(self.root/job/'wrong.txt').write_text('replacement')
        restarted=create_app(self.root).test_client()
        self.assertEqual(restarted.get('/batch/'+batch_id).status_code,200)
        self.assertTrue((self.root/job/'image_0.png').is_file());self.assertFalse((self.root/job/'wrong.txt').exists())

    def test_validation_and_wd_threshold_reanalysis(self):
        base=dict(execute=True,use_wd=True,loras=[])
        for bad in ({'count':21,'ranges':[]},{'count':True,'ranges':[]},{'count':2,'ranges':[dict(field='threshold',start=float('nan'),end=.5)]}):
            with self.assertRaises(ValueError):variants(bad,base)
        analyze=self.mocks();form=self.form(count=2,field='threshold');form['use_wd']='on'
        response=self.client.post('/api/jobs',data=form,headers=self.headers)
        self.assertEqual(response.status_code,202,response.json);self.wait(response.json['batch_id'])
        self.assertEqual(analyze.call_count,2)

    def test_finalization_preserves_favorite_guard_and_updates_both_strengths(self):
        settings=dict(execute=True,use_wd=False,loras=[dict(strength_model=.7,strength_clip=.7)])
        plan=dict(count=3,ranges=[dict(field='strength_model',lora=0,start=-.2,end=.8),dict(field='strength_clip',lora=0,start=.1,end=.9)])
        generated=variants(plan,settings)
        self.assertEqual([(v['loras'][0]['strength_model'],v['loras'][0]['strength_clip']) for v in generated],[(-.2,.1),(.3,.5),(.8,.9)])
        self.mocks();batch_id=self.submit(count=1);batch=self.wait(batch_id);job=batch['job_ids'][0]
        self.store.set_favorite(job,'image_0.png',True)
        result=self.client.post('/api/batches/'+batch_id+'/finalize',json={'selected':[]},headers=self.headers)
        self.assertEqual(result.status_code,409)
        self.assertTrue((self.root/job/'image_0.png').is_file())

    def test_navigation_lists_completed_temporary_galleries_and_static_return_links(self):
        batch_id='9'*32;store=self.app.extensions['batch_store']
        store.save(batch_id,dict(state='review',created_at='2026-10-21T03:00:00+00:00',completed=3,count=3,message='選別待ち',job_ids=[]))
        home=self.client.get('/').get_data(as_text=True)
        normal=self.client.get('/gallery').get_data(as_text=True)
        listing=self.client.get('/batches').get_data(as_text=True)
        temporary=self.client.get('/batch/'+batch_id).get_data(as_text=True)
        self.assertIn('href="/batches"',home);self.assertIn('href="/batches"',normal)
        self.assertIn('href="/batch/'+batch_id+'"',listing)
        self.assertIn('2026/10/21 12:00:00（日本時間）',listing)
        self.assertIn('href="/gallery" data-sidebar-page="gallery"',temporary)
        self.assertIn('data-sidebar-page="batches" title="連続生成レビュー" aria-current="page"',temporary)
        self.assertEqual(self.client.post('/api/batches/'+batch_id+'/finalize',json={'selected':[]},headers=self.headers).status_code,200)
        self.assertIn('未確定の連続生成レビューはありません',self.client.get('/batches').get_data(as_text=True))
        self.assertEqual(self.client.get('/batch/'+batch_id).status_code,404)
