import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from comfyui_wrapper.gallery.history_store import HistoryStore
from comfyui_wrapper.webui import create_app


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=Path(__file__).parent.resolve())
        self.root=Path(self.folder.name)/'results'

    def tearDown(self):
        self.folder.cleanup()

    def test_latest_20_and_durable_details(self):
        store=HistoryStore(self.root/'history.sqlite3')
        for i in range(25):
            store.save(str(i),dict(created_at=f'2026-10-20T00:{i:02d}:00+00:00',state='done',settings={'seed':i}))
        fresh=HistoryStore(self.root/'history.sqlite3')
        records=fresh.latest()
        self.assertEqual(len(records),20)
        self.assertEqual(records[0]['job_id'],'24')
        self.assertEqual(records[-1]['job_id'],'5')
        self.assertEqual(fresh.get('0')['settings']['seed'],0)

    def run_job(self,fail=False,**settings):
        app=create_app(self.root,model=settings.pop('configured_model','qwen3-vl:8b-instruct'))
        app.testing=True
        client=app.test_client()
        image=io.BytesIO()
        Image.new('RGB',(16,32),'blue').save(image,'PNG')
        image.seek(0)
        result=dict(positive='blue dress',negative='blurry',summary_ja='青い服',uncertainties_ja='不明')
        with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=ValueError('mock failure') if fail else None,return_value=result) as analysis_call:
            if fail: app.logger.disabled=True
            form={'target':'animagine','image':(image,'reference.png'),'instruction':'服を青に','seed':'42','analysis_model':'vision:chosen'}
            form.update(settings)
            response=client.post('/api/jobs',data=form,headers={'X-Requested-With':'LLMPC'})
            self.assertEqual(response.status_code,202)
            job_id=response.json['job_id']
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if client.get('/api/jobs/'+job_id).json['state']!='running':break
                time.sleep(.01)
        self.assertEqual(analysis_call.call_args.args[4],app.extensions['app_services'].runtime.analysis_model)
        app.logger.disabled=False
        return job_id

    def test_success_settings_results_survive_restart(self):
        job=self.run_job()
        client=create_app(self.root).test_client()
        detail=client.get('/api/history/'+job).json
        self.assertEqual(detail['settings']['seed'],42)
        self.assertEqual(detail['settings']['analysis_model'],'qwen3-vl:8b-instruct')
        self.assertEqual(detail['settings']['instruction'],'服を青に')
        self.assertEqual(detail['settings']['input_image']['filename'],'reference.png')
        self.assertEqual(detail['generation_settings']['steps'],28)
        self.assertTrue(detail['finished_at'])
        self.assertEqual(detail['state'],'done')
        data=client.get('/api/jobs/'+job).json
        response=client.get(data['downloads']['workflow.json'])
        self.assertEqual(response.status_code,200)
        response.close()

    def test_restore_settings_reexecution_uses_sampler_and_seed(self):
        job=self.run_job(restored_generation=json.dumps({'steps':35,'cfg':5.5}))
        client=create_app(self.root).test_client()
        response=client.get('/api/history/'+job+'/restore')
        self.assertEqual(response.status_code,200)
        payload=response.json
        self.assertEqual(payload['fields']['seed'],42)
        self.assertEqual(payload['generation_settings']['steps'],35)
        self.assertEqual(payload['generation_settings']['cfg'],5.5)
        self.assertNotIn('runtime',payload['fields'])
        self.assertEqual(payload['reference_filename'],'reference.png')
        form={k:('on' if v else '') if type(v) is bool else str(v) for k,v in payload['fields'].items() if v is not None}
        form['restored_generation']=json.dumps(payload['generation_settings'])
        # Reference-free generation is supported; restored prompts are sufficient.
        from tests.support import wait_for_completion
        result=dict(positive='blue',negative='blurry',summary_ja='青',uncertainties_ja='不明')
        with patch('comfyui_wrapper.analysis.generate.analyze',return_value=result):
            text_response=client.post('/api/jobs',data=form,headers={'X-Requested-With':'LLMPC'})
            self.assertEqual(text_response.status_code,202)
            wait_for_completion(client,'/api/jobs/'+text_response.json['job_id'],client.application)
        png=io.BytesIO()
        Image.new('RGB',(16,16)).save(png,'PNG')
        png.seek(0)
        form['image']=(png,'reselected.png')
        result=dict(positive='blue',negative='blurry',summary_ja='青',uncertainties_ja='不明')
        with patch('comfyui_wrapper.analysis.generate.analyze',return_value=result):
            response=client.post('/api/jobs',data=form,headers={'X-Requested-With':'LLMPC'})
            new=response.json['job_id']
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                status=client.get('/api/jobs/'+new).json
                if status['state']!='running':break
                time.sleep(.01)
        workflow=client.get(status['downloads']['workflow.json'])
        sampler=next(n for n in workflow.json['nodes'] if n['type']=='KSampler')
        self.assertEqual(sampler['widgets_values_named']['steps'],35)
        self.assertEqual(sampler['widgets_values_named']['cfg'],5.5)
        self.assertEqual(sampler['widgets_values_named']['seed'],42)
        workflow.close()
        self.assertEqual(client.get('/api/history/missing/restore').status_code,404)
        response=client.get('/api/history/'+job+'/settings')
        self.assertEqual(response.status_code,200)
        self.assertEqual(json.loads(response.data)['settings']['seed'],42)
        response.close()

    def test_failure_still_has_settings(self):
        job=self.run_job(True)
        client=create_app(self.root).test_client()
        detail=client.get('/api/history/'+job).json
        self.assertEqual(detail['state'],'error')
        self.assertEqual(detail['settings']['seed'],42)
        self.assertTrue(detail['finished_at'])
        self.assertEqual(client.get('/api/history').json['items'][0]['job_id'],job)
        self.assertEqual(client.get('/api/history/unknown').status_code,404)

    def test_restart_marks_running_interrupted_without_resubmission(self):
        store=HistoryStore(self.root/'history.sqlite3')
        store.save('old',{'created_at':'2026-10-20T00:00:00+00:00','state':'running','settings':{'seed':1}})
        with patch('urllib.request.urlopen') as network:
            client=create_app(self.root).test_client()
            record=client.get('/api/history/old').json
        self.assertEqual(record['state'],'error')
        self.assertTrue(record['interrupted'])
        self.assertEqual(network.call_count,0)

    def test_older_history_recovers_output_names_from_report(self):
        store=HistoryStore(self.root/'history.sqlite3')
        job='a'*32
        store.save(job,dict(created_at='2026-10-20T00:00:00+00:00',state='done',settings={},images=['image_0.png']))
        directory=self.root/job
        directory.mkdir()
        (directory/'analysis.json').write_text(json.dumps({'comfy_outputs':[
            {'filename':'LLMPC_00042_.png','subfolder':'batch','type':'output'}]}),encoding='utf-8')
        data=create_app(self.root).test_client().get('/api/history/'+job).json
        self.assertEqual(data['output_files'][0]['comfy_filename'],'LLMPC_00042_.png')
        self.assertEqual(data['output_files'][0]['webui_filename'],'image_0.png')




    def test_configured_model_is_used_and_recorded_but_not_replaced_by_form(self):
        job=self.run_job(configured_model='gemma3:4b')
        detail=create_app(self.root).test_client().get('/api/history/'+job).json
        self.assertEqual(detail['settings']['analysis_model'],'gemma3:4b')
        client=create_app(self.root,model='gemma3:12b').test_client()
        self.assertEqual(client.get('/api/history/'+job+'/restore').json['fields']['analysis_model'],'gemma3:12b')
        self.assertEqual(client.get('/api/history/'+job).json['settings']['analysis_model'],'gemma3:4b')

if __name__=='__main__':unittest.main()
