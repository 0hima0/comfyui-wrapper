import base64
import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import MultiDict, FileStorage

from comfyui_wrapper.analysis import generate
from comfyui_wrapper.generation import reference_images
from comfyui_wrapper.webui import create_app


def png(color='red', size=(16,16)):
    stream=io.BytesIO()
    Image.new('RGB',size,color).save(stream,'PNG')
    stream.seek(0)
    return stream


class MultiReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name)/'results'
        self.app=create_app(self.root,wd_dir=Path(self.temp.name))
        self.client=self.app.test_client()
        self.headers={'X-Requested-With':'LLMPC'}

    def tearDown(self):
        self.temp.cleanup()

    def wait(self,job):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            data=self.client.get('/api/jobs/'+job).json
            if data['state']!='running':return data
            time.sleep(.01)
        self.fail('worker did not finish')

    def test_three_images_joint_analysis_generation_metadata_and_restart_restore(self):
        instruction='画像1の人物、画像3の服装、画像7の背景を組み合わせてください。夕方にしてください。'
        roles=[dict(id=1,role='人物・構図'),dict(id=3,role='服装'),dict(id=7,role='背景')]
        form=MultiDict([('image',(png('red'),'person.png')),('image',(png('green'),'clothes.png')),
                       ('image',(png('blue'),'background.png')),('reference_info',json.dumps(roles)),
                       ('instruction',instruction),('execute','on'),('target','animagine'),
                       ('checkpoint','waiIllustriousSDXL_v170.safetensors'),('use_wd','on'),
                       ('rating','auto'),('additional_positive','blue dress')])
        captured=[]
        def chat(url,payload):
            captured.append(copy.deepcopy(payload))
            return {'done':True,'message':{'content':json.dumps(dict(positive='person, garden, sunset',
                negative='blurry',summary_ja='組み合わせ',uncertainties_ja='顔の完全一致は不明'))}}
        def execute(url,graph,workflow,submitted,status,**kwargs):
            self.assertEqual(graph['4']['inputs']['batch_size'],1)
            self.assertEqual(len(kwargs['metadata']['analysis']['reference_images']),3)
            submitted('combined-job')
            return [dict(filename='combined.png',subfolder='',type='output')]
        info={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['waiIllustriousSDXL_v170.safetensors']]}}}}
        with patch('comfyui_wrapper.analysis.generate._chat',side_effect=chat),patch('comfyui_wrapper.integrations.comfy_client.execute',side_effect=execute), \
             patch('comfyui_wrapper.integrations.comfy_client.fetch_image',return_value=png().getvalue()), \
             patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(info).encode())), \
             patch('comfyui_wrapper.analysis.wd_tagger.wd_tags',side_effect=[('red_hair',[dict(category=9,tag='general',score=.9)]),
                 ('red_dress',[dict(category=9,tag='explicit',score=.99)]),('garden',[]),('blue_dress',[])]) as tagger:
            response=self.client.post('/api/jobs',data=form,headers=self.headers)
            self.assertEqual(response.status_code,202)
            job=response.json['job_id'];data=self.wait(job)
        self.assertEqual(data['state'],'done')
        self.assertEqual(len(data['images']),1)
        self.assertEqual(tagger.call_count,4)
        payload=captured[0]['messages'][1]
        self.assertEqual(len(payload['images']),3)
        context=json.loads(payload['content'])
        self.assertEqual(context['user_instruction'],instruction)
        self.assertEqual([row['id'] for row in context['references']],[1,3,7])
        self.assertEqual([row['role'] for row in context['references']],[r['role'] for r in roles])
        self.assertEqual(context['candidate_wd_tags'],'')
        self.assertEqual(context['references'][1]['candidate_wd_tags'],'')
        colors=[]
        for encoded in payload['images']:
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:colors.append(image.getpixel((0,0)))
        self.assertEqual(colors,[(255,0,0),(0,128,0),(0,0,255)])
        response=self.client.get(data['downloads']['image_0.png'])
        with Image.open(io.BytesIO(response.data)) as image:meta=json.loads(image.text['llmpc'])['analysis']
        response.close()
        self.assertEqual(meta['rating']['resolved'],'safe')
        self.assertEqual(meta['rating']['reference_id'],1)
        self.assertEqual(meta['reference_images'][1]['original_candidate_tags'],'red_dress')
        self.assertEqual(meta['prompt_conflicts']['removed_wd_tags'][0]['reference_id'],3)
        fresh=create_app(self.root).test_client()
        restored=fresh.get('/api/history/'+job+'/restore').json
        self.assertEqual(restored['fields']['instruction'],instruction)
        self.assertEqual([r['id'] for r in restored['reference_images']],[1,3,7])
        self.assertEqual([r['filename'] for r in restored['reference_images']],['person.png','clothes.png','background.png'])
        self.assertFalse((self.root/job/'person.png').exists())

    def test_retry_keeps_all_images_roles_ids_and_instruction(self):
        images=[Image.new('RGB',(1600,1200),'red'),Image.new('RGB',(800,1500),'blue')]
        roles=[dict(id=2,role='人物'),dict(id=5,role='服装')]
        seen=[]
        def chat(url,payload):
            seen.append(copy.deepcopy(payload))
            if len(seen)==1:return dict(done=True,done_reason='length',message={'content':''})
            return dict(done=True,message={'content':json.dumps(dict(positive='person',negative='blurry',summary_ja='説明',uncertainties_ja='不明'))})
        try:
            with patch('comfyui_wrapper.analysis.generate._chat',side_effect=chat):
                generate.analyze(images,'画像2の人物に画像5の服装を着せる','','http://localhost','model','animagine',references=roles)
            for attempt,payload in enumerate(seen):
                user=payload['messages'][1]
                self.assertEqual(len(user['images']),2)
                self.assertEqual(json.loads(user['content'])['user_instruction'],'画像2の人物に画像5の服装を着せる')
                self.assertEqual([r['id'] for r in json.loads(user['content'])['references']],[2,5])
                for raw in user['images']:
                    with Image.open(io.BytesIO(base64.b64decode(raw))) as image:
                        self.assertLessEqual(max(image.size),768 if attempt==0 else 512)
        finally:
            for image in images:image.close()

    def test_upload_metadata_validation(self):
        cases=[(5,None),(2,'null'),(2,'[]'),(2,json.dumps([{'id':1},{'id':1}])),
               (1,json.dumps([{'id':True}])),(1,json.dumps([{'id':1,'role':'x'*1001}]))]
        for count,info in cases:
            form=MultiDict([('image',(png(),'ref.png')) for _ in range(count)])
            if info is not None:form.add('reference_info',info)
            response=self.client.post('/api/jobs',data=form,headers=self.headers)
            self.assertEqual(response.status_code,400)
        self.assertFalse(self.app.extensions['generation_lock'].locked())

    def test_partial_decode_failure_closes_previously_loaded_images(self):
        uploads=[FileStorage(png(),filename='good.png'),FileStorage(io.BytesIO(b'invalid'),filename='bad.png')]
        original=reference_images.close_references
        with patch('comfyui_wrapper.generation.reference_images.close_references',wraps=original) as close:
            with self.assertRaises((ValueError,OSError)):
                reference_images.load_references(uploads)
        loaded=close.call_args.args[0]
        self.assertEqual(len(loaded),1)
        with self.assertRaises(ValueError):loaded[0].image.getpixel((0,0))

    def test_total_pixel_limit_and_busy_cleanup(self):
        with patch('comfyui_wrapper.generation.reference_images.MAX_TOTAL_PIXELS',500):
            response=self.client.post('/api/jobs',data=MultiDict([('image',(png(),'a.png')),('image',(png(),'b.png'))]),headers=self.headers)
        self.assertEqual(response.status_code,400)
        loaded=[]
        def load(*args):
            refs=reference_images.load_references(*args);loaded.extend(refs);return refs
        lock=self.app.extensions['generation_lock'];lock.acquire()
        try:
            with patch('comfyui_wrapper.routes.jobs.load_references',side_effect=load):
                response=self.client.post('/api/jobs',data=MultiDict([('image',(png(),'a.png')),('image',(png(),'b.png'))]),headers=self.headers)
            self.assertEqual(response.status_code,409)
            for reference in loaded:
                with self.assertRaises(ValueError):reference.image.getpixel((0,0))
        finally:lock.release()


if __name__=='__main__':unittest.main()
