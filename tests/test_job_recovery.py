"""Recovery only reads saved ComfyUI history; synthetic images and isolated DBs."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.gallery.gallery_cleanup import DeleteBlocked
from comfyui_wrapper.integrations.comfy_client import ComfyError


class JobRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=create_app(self.root);self.client=self.app.test_client()
        self.runner=self.app.extensions['app_services'].runner
        self.job='a'*32;self.prompt='saved-prompt'
        self.folder=self.root/self.job;self.folder.mkdir()
        self.graph={'7':dict(class_type='SaveImage',inputs={})}
        for name,data in [('workflow_api.json',self.graph),('workflow.json',{'nodes':[]}),('analysis.json',{'prompt_id':self.prompt})]:
            (self.folder/name).write_text(json.dumps(data),encoding='utf-8')
        self.runner.history.save(self.job,dict(state='error',created_at='2026-10-01',artifacts_ready=True,prompt_id=self.prompt,
            settings=dict(runtime=dict(comfy_url='http://saved.example:8188')),images=[],output_files=[],
            result=dict(positive='blue',negative='text',summary_ja='合成',uncertainties_ja='')))
        self.descriptors=[dict(filename='first.png',subfolder='',type='output'),dict(filename='second.png',subfolder='',type='output')]
        self.upstream=dict(prompt=[1,self.prompt,self.graph],status=dict(completed=True,status_str='success'),
                           outputs={'7':dict(images=self.descriptors)})
        png=io.BytesIO();Image.new('RGB',(8,8),'blue').save(png,'PNG');self.png=png.getvalue()
        self.headers={'X-Requested-With':'LLMPC'}
        self.url='/api/jobs/'+self.job+'/reconcile'

    def response(self,import_images=False):
        return self.client.post(self.url,json=dict(import_images=import_images),headers=self.headers)

    def test_four_upstream_states_and_no_resubmission(self):
        for history,queue,expected in [({},dict(queue_running=[[0,self.prompt]],queue_pending=[]),'running'),
                ({self.prompt:self.upstream},{},'completed'),({},dict(queue_running=[],queue_pending=[]),'missing')]:
            def api(url,route,**kwargs):
                self.assertEqual(url,'http://saved.example:8188')
                self.assertNotEqual(route,'/prompt')
                return history if route.startswith('/history/') else queue
            with self.subTest(state=expected),patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',side_effect=api):
                self.assertEqual(self.response().json['state'],expected)
        with patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',side_effect=ComfyError('offline')):
            self.assertEqual(self.response().json['state'],'unavailable')
        self.assertEqual(self.runner.history.get(self.job)['images'],[])

    def test_import_is_idempotent_and_preserves_partial_results_on_retry(self):
        with patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',return_value={self.prompt:self.upstream}), \
             patch('comfyui_wrapper.generation.job_recovery.comfy_client.fetch_image',side_effect=[self.png,ComfyError('lost')]):
            with self.assertLogs(self.app.logger,level='ERROR'):
                self.assertEqual(self.response(True).status_code,503)
        self.assertEqual(self.runner.history.get(self.job)['images'],['image_0.png'])
        with patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',return_value={self.prompt:self.upstream}), \
             patch('comfyui_wrapper.generation.job_recovery.comfy_client.fetch_image',return_value=self.png) as fetch:
            self.assertEqual(self.response(True).json['state'],'imported')
            self.assertEqual(self.response(True).json['state'],'imported')
        self.assertEqual(fetch.call_count,1)
        record=self.runner.history.get(self.job)
        self.assertEqual(record['images'],['image_0.png','image_1.png'])
        self.assertEqual(record['state'],'done')
        self.assertTrue((self.folder/'results.zip').is_file())
        self.assertFalse(self.runner.busy.locked())
        self.assertNotIn(self.job,self.runner.records)

    def test_mismatched_history_or_saved_prompt_cannot_mix_images(self):
        for prompt in ([1,'another-prompt',self.graph],[1,self.prompt,{}],None):
            bad=dict(self.upstream,prompt=prompt)
            with patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',return_value={self.prompt:bad}), \
                 patch('comfyui_wrapper.generation.job_recovery.comfy_client.fetch_image') as fetch:
                self.assertEqual(self.response(True).json['state'],'mismatch');fetch.assert_not_called()
        (self.folder/'analysis.json').write_text(json.dumps(dict(prompt_id='another')),encoding='utf-8')
        self.assertEqual(self.response(True).status_code,409)

    def test_guards_concurrent_delete_and_duplicate_import(self):
        self.assertEqual(self.client.post(self.url,json={}).status_code,403)
        self.assertEqual(self.client.post(self.url,json={},headers={**self.headers,'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.client.post(self.url,json={'import_images':'yes'},headers=self.headers).status_code,400)
        def fetch(*args):
            with self.assertRaises(DeleteBlocked):self.app.extensions['gallery_cleanup'].delete(self.job)
            self.assertEqual(self.response(True).status_code,409)
            return self.png
        with patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',return_value={self.prompt:self.upstream}), \
             patch('comfyui_wrapper.generation.job_recovery.comfy_client.fetch_image',side_effect=fetch):
            self.assertEqual(self.response(True).json['state'],'imported')

    def test_temporary_batch_recovery_stays_in_review_and_excludes_finalization(self):
        batch='b'*32
        record=self.runner.history.get(self.job);record.update(temporary=True,batch_id=batch)
        self.runner.history.save(self.job,record)
        self.runner.batches.save(batch,dict(state='error',job_ids=[self.job],count=1,completed=0,created_at='2026-10-01'))
        self.assertEqual(self.client.get('/api/history?recoverable=1').json['items'][0]['job_id'],self.job)
        self.runner.batches.finalize_lock.acquire()
        try:self.assertEqual(self.response(True).status_code,409)
        finally:self.runner.batches.finalize_lock.release()
        with patch('comfyui_wrapper.generation.job_recovery.comfy_client.api',return_value={self.prompt:self.upstream}), \
             patch('comfyui_wrapper.generation.job_recovery.comfy_client.fetch_image',return_value=self.png):
            self.assertEqual(self.response(True).json['state'],'imported')
        self.assertTrue(self.runner.history.get(self.job)['temporary'])
        self.assertEqual(self.runner.batches.get(batch)['state'],'review')
        self.assertEqual(self.client.get('/api/gallery').json['items'],[])
        self.assertFalse(self.runner.batches.finalize_lock.locked())

