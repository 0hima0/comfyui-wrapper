import json
import tempfile
import threading
import io
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from comfyui_wrapper.analysis import analysis_pool
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.infrastructure import job_control
from comfyui_wrapper.settings.app_config import load_config, validate_ollama_urls, validate_keep_alive
from comfyui_wrapper.system.configure_multi_gpu import configure
from comfyui_wrapper.generation.generation_pipeline import analyze_references
from comfyui_wrapper.generation.reference_images import ReferenceImage, close_references
from PIL import Image
from comfyui_wrapper.webui import create_app, parse_args
from werkzeug.datastructures import MultiDict


class AnalysisPoolTests(unittest.TestCase):
    def tearDown(self):job_control.local.control=None

    def test_concurrency_one_task_per_endpoint_and_results_stay_in_order(self):
        barrier=threading.Barrier(2)
        lock=threading.Lock();active={};seen=[];peak=0
        def call(index,url):
            nonlocal peak
            self.assertIsNotNone(job_control.current())
            with lock:
                self.assertNotIn(url,active);active[url]=index;seen.append(index);peak=max(peak,len(active))
            if index<2:barrier.wait(timeout=3)
            with lock:active.pop(url)
            return index
        tasks=[(str(i),lambda url,i=i:call(i,url)) for i in range(5)]
        values,execution=analysis_pool.run(tasks,['gpu0','gpu1'],lambda _:None)
        self.assertEqual(values,list(range(5)));self.assertEqual(sorted(seen),list(range(5)))
        self.assertEqual(peak,2)
        self.assertEqual(execution['mode'],'parallel')
        self.assertEqual([r['task'] for r in execution['tasks']],[str(i) for i in range(5)])

    def test_failure_cancels_peer_and_does_not_start_more_tasks(self):
        barrier=threading.Barrier(2);peer_stopped=threading.Event()
        def fail(url):
            barrier.wait(timeout=3);raise generate.AnalysisError('worker failure')
        def peer(url):
            barrier.wait(timeout=3)
            self.assertTrue(job_control.current().event.wait(3))
            peer_stopped.set();job_control.check()
        def never(url):self.fail('a later task must not start')
        with self.assertRaisesRegex(generate.AnalysisError,'worker failure'):
            analysis_pool.run([('bad',fail),('peer',peer),('later',never)],['gpu0','gpu1'],lambda _:None)
        self.assertTrue(peer_stopped.is_set())

    def test_parent_cancel_reaches_both_workers(self):
        parent=job_control.JobControl();job_control.local.control=parent
        barrier=threading.Barrier(2);stopped=[]
        def call(url):
            barrier.wait(timeout=3);parent.event.set()
            self.assertTrue(job_control.current().event.wait(3));stopped.append(url);job_control.check()
        with self.assertRaises(job_control.JobCancelled):
            analysis_pool.run([('a',call),('b',call)],['gpu0','gpu1'],lambda _:None)
        self.assertEqual(sorted(stopped),['gpu0','gpu1'])
        self.assertIs(job_control.current(),parent)

    def test_config_validation_and_preserving_existing_config_with_backup(self):
        self.assertEqual(validate_ollama_urls(['http://localhost:11434/']),['http://localhost:11434'])
        for invalid in ('url', ['ftp://server'],['http://a','http://a/'],[None],['http://a?x=1']):
            with self.assertRaises(ValueError):validate_ollama_urls(invalid)
        for value in (-1,0,120,'10m','0'):self.assertEqual(validate_keep_alive(value),value)
        for value in (True,'forever','1.5m',-2):
            with self.assertRaises(ValueError):validate_keep_alive(value)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            path=Path(temp)/'config.json'
            old=dict(wd_dir='/models/wd',comfy_url='http://comfy:8188',checkpoint_families={'custom':'sdxl'})
            path.write_text(json.dumps(old),encoding='utf-8')
            backup=configure(path)
            self.assertEqual(json.loads(backup.read_text(encoding='utf-8')),old)
            updated=load_config(path)
            self.assertEqual(updated['comfy_url'],old['comfy_url'])
            self.assertEqual(updated['checkpoint_families'],old['checkpoint_families'])
            self.assertEqual(updated['ollama_keep_alive'],'10m')
            self.assertEqual(len(updated['ollama_urls']),2)
            cli_config=Path(temp)/'cli.json'
            cli_config.write_text('{}',encoding='utf-8')
            args=parse_args(['--config',str(cli_config),'--ollama-urls','http://a:11434','http://b:11435','--ollama-keep-alive','5m'])
            self.assertEqual(args.ollama_urls,['http://a:11434','http://b:11435'])
            self.assertEqual(args.ollama_keep_alive,'5m')

    def test_web_stop_cancels_parallel_workers_before_workflow_and_releases_job(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            app=create_app(Path(temp),ollama_urls=['http://gpu0','http://gpu1'],ollama_keep_alive='10m')
            client=app.test_client();barrier=threading.Barrier(2);entered=threading.Event();stopped=[]
            def analyze(*args,**kwargs):
                barrier.wait(timeout=3);entered.set()
                self.assertTrue(job_control.current().event.wait(3))
                stopped.append(args[3]);job_control.check()
            def png():
                stream=io.BytesIO();Image.new('RGB',(8,8)).save(stream,'PNG');stream.seek(0);return stream
            form=MultiDict([('image',(png(),'one.png')),('image',(png(),'two.png')),('target','animagine'),
                            ('checkpoint','waiIllustriousSDXL_v170.safetensors'),('preserve_people','on')])
            headers={'X-Requested-With':'LLMPC'}
            with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=analyze),patch('comfyui_wrapper.generation.generation_jobs.build_workflow') as build:
                response=client.post('/api/jobs',data=form,headers=headers)
                self.assertEqual(response.status_code,202,response.json)
                job=response.json['job_id'];self.assertTrue(entered.wait(3))
                self.assertEqual(client.post('/api/jobs/'+job+'/cancel',headers=headers).status_code,202)
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    record=client.get('/api/jobs/'+job).json
                    if record['state']!='running' and not app.extensions['generation_lock'].locked():break
                    time.sleep(.01)
                self.assertEqual(record['state'],'cancelled',record)
                self.assertFalse(app.extensions['generation_lock'].locked())
                self.assertEqual(sorted(stopped),['http://gpu0','http://gpu1'])
                self.assertEqual(record['settings']['runtime']['ollama_keep_alive'],'10m')
                build.assert_not_called()

    def test_pipeline_parallel_calls_preserve_reference_outfits_and_keep_alive(self):
        references=[ReferenceImage(2,'red.png','',Image.new('RGB',(8,8),'red')),
                    ReferenceImage(7,'blue.png','',Image.new('RGB',(8,8),'blue'))]
        settings=dict(additional_positive='',additional_negative='',loras=[],use_wd=False,
                      instruction='庭で並ぶ',analysis_model='qwen3-vl:8b-instruct',target='animagine',profile='wai17',
                      preserve_people=True,use_quality_tags=False,rating='none',
                      ollama_urls=['gpu0','gpu1'],ollama_keep_alive='10m')
        def analyze(image,instruction,tags,url,model,target,**kwargs):
            self.assertEqual(kwargs['keep_alive'],'10m')
            text='shared garden' if image is None or isinstance(image,list) else ('red jacket' if image.getpixel((0,0))==(255,0,0) else 'blue dress')
            return dict(positive=text,negative='blurry',summary_ja='人物',uncertainties_ja='')
        try:
            with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=analyze):
                result=analyze_references(references,settings,None,'legacy',lambda *_:None)
            self.assertEqual([p['reference_id'] for p in result['people']],[2,7])
            self.assertEqual([p['positive'] for p in result['people']],['red jacket','blue dress'])
            self.assertEqual(len(result['analysis_execution']['tasks']),3)
        finally:close_references(references)
