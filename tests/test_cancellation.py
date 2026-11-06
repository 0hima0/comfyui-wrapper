import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.infrastructure import job_control
from comfyui_wrapper.webui import create_app


class CancellationTests(unittest.TestCase):
    def tearDown(self):
        job_control.local.control = None

    def test_ollama_stream_is_assembled(self):
        job_control.local.control = job_control.JobControl()
        rows = [dict(message=dict(content='{"positive":')),
                dict(done=True, done_reason='stop', eval_count=5, message=dict(content='"blue"}'))]
        with patch('urllib.request.urlopen', return_value=io.BytesIO(
                b'\n'.join(json.dumps(row).encode() for row in rows))) as call:
            reply = generate._chat('http://ollama', dict(model='test', stream=False))
        self.assertTrue(json.loads(call.call_args.args[0].data)['stream'])
        self.assertEqual(json.loads(reply['message']['content']), dict(positive='blue'))
        self.assertEqual(reply['eval_count'], 5)

    def test_cancelled_ollama_never_retries(self):
        control = job_control.JobControl()
        job_control.local.control = control
        class Stream(io.BytesIO):
            def __next__(self):
                control.event.set()
                return b'{"message":{"content":"partial"}}\n'
        with patch('urllib.request.urlopen', return_value=Stream()) as call:
            with self.assertRaises(job_control.JobCancelled):
                generate.analyze(Image.new('RGB', (8,8)), '', '', 'http://ollama', 'model', 'anima')
        self.assertEqual(call.call_count, 1)

    def test_cancel_disconnects_only_current_ollama_stream(self):
        from types import SimpleNamespace
        control = job_control.JobControl()
        job_control.local.control = control
        closed = threading.Event()
        class Stream(io.BytesIO):
            fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(shutdown=lambda _:closed.set())))
            def __next__(self):
                control.event.set()
                if not closed.wait(2):
                    raise AssertionError('stream was not disconnected')
                raise OSError('disconnected')
        with patch('urllib.request.urlopen', return_value=Stream()) as call:
            with self.assertRaises(job_control.JobCancelled):
                generate._chat('http://ollama', dict(model='test'))
        self.assertTrue(closed.is_set())
        self.assertEqual(call.call_count, 1)

    def test_comfy_cancel_is_scoped_and_waits_for_queue_exit(self):
        control = job_control.JobControl()
        job_control.local.control = control
        calls = []
        queues = iter([dict(queue_running=[[0,'own']], queue_pending=[]),
                       dict(queue_running=[[1,'other']], queue_pending=[])])
        def api(url, route, payload=None, **kwargs):
            calls.append((route,payload))
            if route == '/object_info': return {}
            if route == '/prompt': return dict(prompt_id='own')
            if route.endswith('/cancel'): return dict(cancelled=True)
            if route == '/queue': return next(queues)
            if route.startswith('/history/'): return {}
            self.fail(route)
        with patch('comfyui_wrapper.integrations.comfy_client.api', side_effect=api):
            with self.assertRaises(job_control.JobCancelled):
                comfy_client.execute('http://comfy', {}, {}, lambda _:control.event.set(), lambda _:None, interval=0)
        self.assertEqual(sum(route=='/api/jobs/own/cancel' for route,_ in calls), 1)
        self.assertEqual(sum(route=='/prompt' for route,_ in calls), 1)
        self.assertFalse(any(route in ('/interrupt','/free') for route,_ in calls))

    def test_comfy_stop_failure_is_reported(self):
        control = job_control.JobControl()
        job_control.local.control = control
        def api(url, route, payload=None, **kwargs):
            if route == '/object_info': return {}
            if route == '/prompt': return dict(prompt_id='own')
            raise comfy_client.ComfyError('HTTP 404')
        with patch('comfyui_wrapper.integrations.comfy_client.api', side_effect=api):
            with self.assertRaisesRegex(comfy_client.ComfyError, '停止要求に失敗'):
                comfy_client.execute('http://comfy', {}, {}, lambda _:control.event.set(), lambda _:None)

    def test_web_cancel_lifecycle_security_and_history(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            app = create_app(Path(temp))
            client = app.test_client()
            entered = threading.Event()
            def analysis(*args, **kwargs):
                entered.set()
                self.assertTrue(job_control.current().event.wait(3))
                # Mimic a CPU stage finishing: cancellation must prevent the next stage.
                return dict(result=dict(positive='blue'))
            image = io.BytesIO()
            Image.new('RGB', (8,8)).save(image, 'PNG');image.seek(0)
            with patch('comfyui_wrapper.generation.generation_jobs.analyze_references', side_effect=analysis), patch('comfyui_wrapper.generation.generation_jobs.build_workflow') as build:
                response = client.post('/api/jobs', data=dict(target='animagine',image=(image,'sample.png')),
                                       headers={'X-Requested-With':'LLMPC'})
                job = response.json['job_id'];route = '/api/jobs/'+job+'/cancel'
                self.assertTrue(entered.wait(3))
                self.assertEqual(client.post(route).status_code,403)
                self.assertEqual(client.post(route,headers={'X-Requested-With':'LLMPC','Origin':'http://evil'}).status_code,403)
                self.assertEqual(client.post(route,headers={'X-Requested-With':'LLMPC'}).status_code,202)
                deadline = time.monotonic()+3
                while time.monotonic()<deadline:
                    record=client.get('/api/jobs/'+job).json
                    if record['state']!='running' and not app.extensions['generation_lock'].locked(): break
                    time.sleep(.01)
                self.assertEqual(record['state'],'cancelled')
                self.assertIn('finished_at',record)
                self.assertFalse(app.extensions['generation_lock'].locked())
                build.assert_not_called()
                self.assertFalse(client.post(route,headers={'X-Requested-With':'LLMPC'}).json['cancel_requested'])
                self.assertEqual(client.post('/api/jobs/missing/cancel',headers={'X-Requested-With':'LLMPC'}).status_code,404)
            restarted=create_app(Path(temp)).test_client()
            self.assertEqual(restarted.get('/api/history/'+job).json['state'],'cancelled')

