import json
import unittest
import io
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, Mock
from PIL import Image

from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.integrations.comfy_progress import ComfyProgress, open_socket
from tests.support import comfy_graph, comfy_schema
from comfyui_wrapper.webui import create_app


class ProgressTests(unittest.TestCase):
    def tracker(self):
        with patch('comfyui_wrapper.integrations.comfy_progress.open_socket',return_value=Mock()) as connect:
            tracker=ComfyProgress('http://localhost','client',{'5':{'class_type':'KSampler'},'6':{'class_type':'VAEDecode'}})
        tracker.bind('ours')
        return tracker

    def event(self,tracker,kind,**data):
        return tracker.event(dict(type=kind,data=data))

    def test_progress_belongs_to_own_sampler_only(self):
        tracker=self.tracker()
        self.assertIsNone(self.event(tracker,'progress',prompt_id='ours',node='5',value=1,max=28))
        self.assertIsNone(self.event(tracker,'executing',prompt_id='other',node='5'))
        self.event(tracker,'execution_start',prompt_id='ours')
        self.event(tracker,'executing',prompt_id='ours',node='5')
        self.assertIsNone(self.event(tracker,'progress',prompt_id='other',node='5',value=28,max=28))
        measured=self.event(tracker,'progress',prompt_id='ours',node='5',value=12,max=28)
        self.assertEqual((measured['current'],measured['total']),(12,28))
        # Legacy progress without prompt_id is accepted only after our executing event.
        self.assertEqual(self.event(tracker,'progress',value=13,max=28)['current'],13)
        decoded=self.event(tracker,'executing',prompt_id='ours',node='6')
        self.assertNotIn('current',decoded)
        self.assertIsNone(self.event(tracker,'progress',prompt_id='ours',node='6',value=1,max=1))
        self.event(tracker,'executing',prompt_id='ours',node=None)
        self.assertIsNone(self.event(tracker,'progress',value=28,max=28))

    def test_invalid_messages_do_not_create_percentages(self):
        tracker=self.tracker()
        self.event(tracker,'executing',prompt_id='ours',node='5')
        for value,maximum in [(True,28),(-1,28),(29,28),(1,0),(float('nan'),28),(1,float('inf')),('12',28)]:
            self.assertIsNone(self.event(tracker,'progress',prompt_id='ours',node='5',value=value,max=maximum))
        self.assertIsNone(tracker.event([]))
        self.assertIsNone(tracker.event({'type':'progress','data':None}))

    def test_poll_ignores_binary_and_other_jobs_and_resets_on_disconnect(self):
        tracker=self.tracker();socket=tracker.socket
        socket.recv.side_effect=[b'preview','invalid JSON',json.dumps(dict(type='executing',data=dict(prompt_id='ours',node='5'))),
            json.dumps(dict(type='progress',data=dict(prompt_id='ours',node='5',value=14,max=28))),TimeoutError(),OSError('closed')]
        update=tracker.poll()
        self.assertEqual(update['current'],14)
        disconnected=tracker.poll()
        self.assertNotIn('current',disconnected)
        socket.close.assert_called_once()
        self.assertIsNone(tracker.socket)

    def test_ws_url_and_socket_cleanup_on_setup_error(self):
        socket=Mock();module=Mock();module.create_connection.return_value=socket
        with patch.dict('sys.modules',{'websocket':module}):
            self.assertIs(open_socket('https://example.test/comfy','unique'),socket)
        self.assertEqual(module.create_connection.call_args.args[0],'wss://example.test/comfy/ws?clientId=unique')
        socket.settimeout.side_effect=OSError('timeout setup failed')
        with patch.dict('sys.modules',{'websocket':module}):
            self.assertIsNone(open_socket('http://localhost:8188','unique'))
        socket.close.assert_called_once()

    def test_execute_delivers_steps_closes_socket_and_never_resubmits(self):
        workflow,graph=comfy_graph()
        frames=[json.dumps(dict(type='executing',data=dict(prompt_id='ours',node='5'))),
                json.dumps(dict(type='progress',data=dict(prompt_id='ours',node='5',value=12,max=28)))]
        socket=Mock();socket.recv.side_effect=frames+[TimeoutError()]
        outputs=[{'filename':'generated.png'}]
        replies=[comfy_schema(graph),{'prompt_id':'ours'}, {'ours':{'status':{'completed':True},'outputs':{'7':{'images':outputs}}}}]
        steps=[]
        with patch('comfyui_wrapper.integrations.comfy_progress.open_socket',return_value=socket) as connect,patch('comfyui_wrapper.integrations.comfy_client.api',side_effect=replies) as api:
            result=comfy_client.execute('http://localhost',graph,workflow,lambda _:None,lambda _:None,on_progress=steps.append)
        self.assertEqual(result,outputs)
        self.assertEqual(steps[0]['current'],12)
        self.assertEqual(connect.call_args.args[1],api.call_args_list[1].args[2]['client_id'])
        self.assertEqual(sum(call.args[1]=='/prompt' for call in api.call_args_list),1)
        socket.close.assert_called_once()

    def test_missing_websocket_falls_back_to_history(self):
        workflow,graph=comfy_graph()
        replies=[comfy_schema(graph),{'prompt_id':'ours'},{'ours':{'status':{'completed':True},'outputs':{'7':{'images':[{'filename':'x.png'}]}}}}]
        with patch('comfyui_wrapper.integrations.comfy_progress.open_socket',return_value=None),patch('comfyui_wrapper.integrations.comfy_client.api',side_effect=replies):
            result=comfy_client.execute('http://localhost',graph,workflow,lambda _:None,lambda _:None,on_progress=lambda _:None)
        self.assertEqual(result[0]['filename'],'x.png')

    def test_api_persists_stage_and_partial_steps_on_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            app=create_app(Path(folder));client=app.test_client();observed=[]
            tracked=[]
            def snapshot():
                if not tracked:tracked.append(next(iter(app.extensions['image_jobs'])))
                job=tracked[0]
                return client.get('/api/jobs/'+job).json
            def analyze(*args,**kwargs):
                observed.append(snapshot()['progress']['stage'])
                return dict(positive='blue dress',negative='blurry',summary_ja='青',uncertainties_ja='不明')
            def execute(url,graph,workflow,submitted,status,**kwargs):
                submitted('ours');status('ComfyUIのキュー待ち')
                observed.append(snapshot()['progress']['stage'])
                kwargs['on_progress'](dict(stage='generate',detail='生成中',current=12,total=28))
                data=snapshot();self.assertEqual(data['progress']['current'],12)
                raise comfy_client.ComfyError('test OOM')
            info={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['model.safetensors']]}}}}
            image=io.BytesIO();Image.new('RGB',(16,16)).save(image,'PNG');image.seek(0)
            with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=analyze),patch('comfyui_wrapper.integrations.comfy_client.execute',side_effect=execute), \
                 patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(info).encode())),self.assertLogs(app.logger,level='ERROR'):
                response=client.post('/api/jobs',headers={'X-Requested-With':'LLMPC'},data={
                    'target':'animagine','checkpoint':'model.safetensors','execute':'on','image':(image,'ref.png')})
                self.assertEqual(response.status_code,202)
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    data=snapshot()
                    if data['state']!='running':break
                    time.sleep(.01)
            self.assertEqual(observed,['analysis','queue'])
            self.assertEqual(data['state'],'error')
            self.assertEqual(data['progress']['stage'],'generate')
            fresh=create_app(Path(folder)).test_client().get('/api/jobs/'+response.json['job_id']).json
            self.assertEqual(fresh['progress']['current'],12)


if __name__=='__main__':unittest.main()
