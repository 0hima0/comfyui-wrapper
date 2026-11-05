"""Collection search, image annotations, recommendations and matrix planning."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.generation.batch_generation import variants

class CollectionFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=create_app(self.root);self.client=self.app.test_client()
        self.history=self.app.extensions['app_services'].history
        self.headers={'X-Requested-With':'LLMPC'}

    def image(self,index,**changes):
        job=f'{index:032x}';directory=self.root/job;directory.mkdir()
        for filename in ['one.png','two.png']:Image.new('RGB',(8,8),'blue').save(directory/filename)
        record=dict(created_at='2026-10-01T15:10:00+00:00',state='done',artifacts_ready=True,images=['one.png','two.png'],
                    settings=dict(checkpoint='model-A.safetensors',instruction='park bench',loras=[dict(name='sdxl/alpha.safetensors')]),
                    result=dict(positive='sunlight, park',negative='text'))
        record.update(changes);self.history.save(job,record);return job

    def test_version_two_database_migrates_with_backup_and_preserves_payload(self):
        from comfyui_wrapper.infrastructure.database import SCHEMAS,connection
        from comfyui_wrapper.gallery.history_store import HistoryStore
        path=self.root/'legacy.sqlite3'
        with connection(path) as db:
            for step in SCHEMAS['history'][:2]:
                for sql in step:db.execute(sql)
            db.execute('PRAGMA user_version=2')
            record=dict(created_at='2026-01-01',state='done',images=['a.png'])
            db.execute('INSERT INTO executions VALUES(?,?,?)',('old','2026-01-01',json.dumps(record)))
            db.execute('INSERT INTO image_favorites VALUES(?,?)',('old','a.png'))
        store=HistoryStore(path)
        self.assertEqual(store.get('old'),record)
        self.assertEqual(len(list(self.root.glob('legacy.pre-v4.*.sqlite3'))),1)
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT * FROM image_favorites').fetchall(),[('old','a.png')])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
        store.annotate('old','a.png','preserved',['label'])
        self.assertEqual(store.annotations('old')['a.png']['note'],'preserved')

    def test_image_annotations_are_independent_searchable_and_survive_reopen(self):
        job=self.image(1);url=f'/api/gallery/{job}/one.png/annotation'
        response=self.client.put(url,json=dict(note='服装が良い',labels=[' 衣装 ','候補','候補']),headers=self.headers)
        self.assertEqual(response.json,dict(note='服装が良い',labels=['衣装','候補']))
        self.assertEqual(self.client.get('/api/gallery?q=服装').json['items'][0]['filename'],'one.png')
        self.assertEqual(len(self.client.get('/api/gallery?label=候補').json['items']),1)
        self.assertEqual(len(self.client.get('/api/gallery?q=park').json['items']),2)
        self.assertEqual(self.history.annotations(job)['one.png']['labels'],['衣装','候補'])
        from comfyui_wrapper.gallery.history_store import HistoryStore
        self.assertEqual(HistoryStore(self.history.path).annotations(job)['one.png']['note'],'服装が良い')
        self.assertEqual(self.client.get('/api/gallery?favorites=1').json['items'],[])
        self.assertEqual(self.client.put(url,json=dict(note='x'*4001,labels=[]),headers=self.headers).status_code,400)
        self.assertEqual(self.client.put(url,json=dict(note='',labels=['a']*21),headers=self.headers).status_code,400)
        self.assertEqual(self.client.put(url,json=dict(note='',labels=[42]),headers=self.headers).status_code,400)
        self.client.delete('/api/gallery/'+job,headers=self.headers)
        self.assertEqual(self.history.annotations(job),{})

    def test_filters_apply_before_pagination_and_use_literal_parameters(self):
        for index in range(1,28):
            self.image(index,settings=dict(checkpoint='other.safetensors',instruction='indoors',loras=[]),result=dict(positive='indoors',negative='text'))
        target=self.image(28,created_at='2026-10-01T15:00:00+00:00')
        for query in ['model=model-A','lora=ALPHA','q=sunlight','after=2026-10-02&before=2026-10-02']:
            data=self.client.get('/api/gallery?'+query).json
            if query.startswith('after'):self.assertEqual(len(data['items']),48)
            else:self.assertEqual({item['job_id'] for item in data['items']},{target})
        self.assertEqual(self.client.get('/api/gallery?model=%25').json['items'],[])
        self.assertEqual(self.client.get('/api/gallery?q=%27%20OR%201=1--').json['items'],[])
        self.assertEqual(self.client.get('/api/gallery?after=2026-10-03&before=2026-10-02').status_code,400)
        self.assertEqual(self.client.get('/api/gallery?after=invalid').status_code,400)
        self.assertEqual(self.client.get('/api/gallery?before=2026-10-01').json['items'],[])

    def test_annotations_reject_temporary_missing_and_running_images(self):
        job=self.image(1,temporary=True)
        url=f'/api/gallery/{job}/one.png/annotation'
        self.assertEqual(self.client.put(url,json=dict(note='',labels=[]),headers=self.headers).status_code,409)
        self.assertEqual(self.client.put(url,json=dict(note='',labels=[])).status_code,403)
        self.assertEqual(self.client.put(url.replace('one.png','missing.png'),json=dict(note='',labels=[]),headers=self.headers).status_code,404)

    def test_recommendations_are_scoped_validated_and_can_be_deleted(self):
        model=dict(steps=28,cfg=5,sampler_name='euler',scheduler='normal',clip_skip=1,negative='text')
        lora=dict(strength_model=.6,strength_clip=.4)
        for kind,values in [('model',model),('lora',lora)]:
            key=dict(kind=kind,name='same.safetensors')
            self.assertEqual(self.client.put('/api/recommendations',json=dict(**key,values=values),headers=self.headers).json['values'],values)
            self.assertEqual(self.client.get('/api/recommendations',query_string=key).json['values'],values)
        self.assertIsNone(self.client.get('/api/recommendations?kind=model&name=other').json['values'])
        for bad in [dict(model,cfg=101),dict(model,steps=2.5),dict(model,extra=1),dict(model,cfg=True)]:
            self.assertEqual(self.client.put('/api/recommendations',json=dict(kind='model',name='bad',values=bad),headers=self.headers).status_code,400)
        self.assertEqual(self.client.delete('/api/recommendations',json=dict(kind='model',name='same.safetensors'),headers=self.headers).status_code,200)
        self.assertIsNone(self.client.get('/api/recommendations?kind=model&name=same.safetensors').json['values'])
        self.assertEqual(self.client.get('/api/recommendations?kind=invalid&name=x').status_code,400)

class MatrixPlanTests(unittest.TestCase):
    def setUp(self):
        self.settings=dict(execute=True,use_wd=True,threshold=.35,seed=42,loras=[dict(name='sdxl/x',strength_model=.7,strength_clip=.7)],generation_effective=dict(cfg=5,steps=28))
        self.plan=dict(mode='matrix',count=6,ranges=[dict(field='cfg',start=4,end=6,points=3),dict(field='strength_model',lora=0,start=.4,end=.8,points=2)])

    def test_cartesian_product_positions_and_immutable_input(self):
        original=copy.deepcopy(self.settings);rows=variants(self.plan,self.settings)
        self.assertEqual([(r['generation_effective']['cfg'],r['loras'][0]['strength_model']) for r in rows],[(4,.4),(5,.4),(6,.4),(4,.8),(5,.8),(6,.8)])
        self.assertEqual([(r['batch_cell']['row'],r['batch_cell']['column']) for r in rows],[(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)])
        self.assertEqual({r['seed'] for r in rows},{42});self.assertEqual(self.settings,original)

    def test_matrix_limits_and_duplicate_steps(self):
        for plan in [dict(self.plan,count=5),dict(self.plan,count=20,ranges=[dict(field='cfg',start=4,end=6,points=5),dict(field='steps',start=20,end=30,points=5)]),dict(self.plan,count=3,ranges=[dict(field='steps',start=20,end=21,points=3)]),dict(self.plan,count=2,ranges=[dict(field='cfg',start=4,end=4,points=2)])]:
            with self.assertRaises(ValueError):variants(plan,self.settings)
        plan=dict(mode='matrix',count=3,ranges=[dict(field='steps',start=20,end=24,points=3)])
        self.assertEqual([r['generation_effective']['steps'] for r in variants(plan,self.settings)],[20,22,24])

    def test_linear_mode_retains_old_count_and_supports_cfg(self):
        plan=dict(count=3,ranges=[dict(field='cfg',start=4,end=8)])
        self.assertEqual([r['generation_effective']['cfg'] for r in variants(plan,self.settings)],[4,6,8])
