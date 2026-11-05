import tempfile
import unittest
from pathlib import Path
from comfyui_wrapper.webui import create_app


class LoraFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)
        self.client = create_app(self.root).test_client()
        self.headers = {'X-Requested-With': 'LLMPC'}

    def tearDown(self):
        self.temp.cleanup()


class LoraRegistryTests(LoraFixture, unittest.TestCase):

    def test_save_update_restart_delete_and_distinct_paths(self):
        for name, trigger in [('a/style.safetensors','style_a'), ('b/style.safetensors','style_b')]:
            result = self.client.put('/api/lora-triggers', json={
                'name': name, 'trigger': trigger, 'url': 'https://example.com/model', 'note': '配布元の指定'
            }, headers=self.headers)
            self.assertEqual(result.status_code, 200)
        fresh = create_app(self.root).test_client()
        records = fresh.get('/api/lora-triggers').json['records']
        self.assertEqual(records['a/style.safetensors']['trigger'], 'style_a')
        self.assertEqual(records['b/style.safetensors']['trigger'], 'style_b')
        fresh.put('/api/lora-triggers', json={'name':'a/style.safetensors','trigger':''}, headers=self.headers)
        self.assertEqual(fresh.get('/api/lora-triggers').json['records']['a/style.safetensors']['trigger'], '')
        fresh.delete('/api/lora-triggers', json={'name':'a/style.safetensors'}, headers=self.headers)
        self.assertEqual(list(fresh.get('/api/lora-triggers').json['records']), ['b/style.safetensors'])

    def test_invalid_and_cross_origin_writes_do_not_change_records(self):
        self.assertEqual(self.client.put('/api/lora-triggers', json={'name':'x'}).status_code, 403)
        self.assertEqual(self.client.put('/api/lora-triggers', json={'name':'x'},
            headers={**self.headers,'Origin':'https://another.example'}).status_code, 403)
        for value in ([], {'name':''}, {'name':'x','trigger':3}, {'name':'x','trigger':'x'*2001},
                      {'name':'x','url':'javascript:alert(1)'}):
            self.assertEqual(self.client.put('/api/lora-triggers', json=value, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get('/api/lora-triggers').json['records'], {})

    def test_manager_page_and_script(self):
        self.assertEqual(self.client.get('/loras').status_code, 200)
        with self.client.get('/static/lora_manager.js') as response:
            self.assertEqual(response.status_code, 200)


    def test_management_tags_are_validated_persisted_and_preserved_for_older_clients(self):
        row=dict(name='sdxl/style.safetensors',trigger='token',note='memo',tags=[' 人物 ','人物','Style','style'])
        response=self.client.put('/api/lora-triggers',json=row,headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['records'][row['name']]['tags'],['人物','Style'])
        # An old client may edit the note without sending the new tags field.
        self.client.put('/api/lora-triggers',json=dict(name=row['name'],note='new'),headers=self.headers)
        fresh=create_app(self.root).test_client()
        self.assertEqual(fresh.get('/api/lora-triggers').json['records'][row['name']]['tags'],['人物','Style'])
        for tags in [None,'text',['x'*41],['a']*21,[''],[42],['a\nb']]:
            with self.subTest(tags=tags):self.assertEqual(self.client.put('/api/lora-triggers',json=dict(row,tags=tags),headers=self.headers).status_code,400)
        self.assertEqual(self.client.put('/api/lora-triggers',json=dict(row,tags=[]),headers=self.headers).json['records'][row['name']]['tags'],[])

    def test_lora_schema_upgrade_preserves_existing_metadata_and_samples(self):
        import json
        from comfyui_wrapper.infrastructure.database import connection,SCHEMAS
        from comfyui_wrapper.models.lora_store import LoraStore
        path=self.root/'legacy-loras.sqlite3'
        with connection(path) as db:
            for sql in SCHEMAS['loras'][0]:db.execute(sql)
            db.execute('PRAGMA user_version=1')
            db.execute('INSERT INTO loras VALUES(?,?,?,?)',('sdxl/old','trigger','https://example.com','note'))
            db.execute('INSERT INTO lora_samples VALUES(?,?,?,?,?,?,?)',('sample','sdxl/old','sample.png','png','image/png',8,8))
        store=LoraStore(path)
        self.assertEqual(store.all()['sdxl/old'],dict(trigger='trigger',url='https://example.com',note='note',tags=[],recommended_prompt=''))
        self.assertEqual(store.samples('sdxl/old')[0]['id'],'sample')
        self.assertEqual(len(list(self.root.glob('legacy-loras.pre-v3.*.sqlite3'))),1)


class RecommendedPromptTests(LoraFixture, unittest.TestCase):
    def test_v2_upgrade_preserves_tags_metadata_samples_and_backup(self):
        import json
        from comfyui_wrapper.infrastructure.database import connection, SCHEMAS
        from comfyui_wrapper.models.lora_store import LoraStore
        path=self.root/'v2-loras.sqlite3'
        with connection(path) as db:
            for step in SCHEMAS['loras'][:2]:
                for sql in step:db.execute(sql)
            db.execute('PRAGMA user_version=2')
            db.execute('INSERT INTO loras VALUES(?,?,?,?,?)',('sdxl/old','token','https://example.com','memo',json.dumps(['人物','Style'])))
            db.execute('INSERT INTO lora_samples VALUES(?,?,?,?,?,?,?)',('sample','sdxl/old','sample.png','png','image/png',8,8))
        store=LoraStore(path)
        expected=dict(trigger='token',url='https://example.com',note='memo',tags=['人物','Style'],recommended_prompt='')
        self.assertEqual(store.all()['sdxl/old'],expected)
        backups=list(self.root.glob('v2-loras.pre-v3.*.sqlite3'))
        self.assertEqual(len(backups),1)
        with connection(backups[0]) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(json.loads(db.execute('SELECT tags FROM loras').fetchone()[0]),['人物','Style'])
            self.assertEqual(db.execute('SELECT id FROM lora_samples').fetchone()[0],'sample')
        store.save('sdxl/old','token','https://example.com','memo',recommended_prompt='日本語\nsoft light')
        self.assertEqual(LoraStore(path).all()['sdxl/old']['recommended_prompt'],'日本語\nsoft light')
        self.assertEqual(store.samples('sdxl/old')[0]['id'],'sample')
        self.assertEqual(len(list(self.root.glob('v2-loras.pre-v3.*.sqlite3'))),1)

    def test_prompt_persists_without_changing_trigger_and_old_client_preserves_it(self):
        name='sdxl/example.safetensors'
        row=dict(name=name,trigger='token',note='memo',recommended_prompt='soft light, detailed clothing')
        response=self.client.put('/api/lora-triggers',json=row,headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.client.put('/api/lora-triggers',json=dict(name=name,trigger='token',note='new'),headers=self.headers)
        fresh=create_app(self.root).test_client()
        saved=fresh.get('/api/lora-triggers').json['records'][name]
        self.assertEqual(saved['recommended_prompt'],row['recommended_prompt'])
        self.assertEqual(saved['trigger'],'token')
        for value in (None,42,'x'*8001,'a\x00b'):
            self.assertEqual(self.client.put('/api/lora-triggers',json=dict(row,recommended_prompt=value),headers=self.headers).status_code,400)
        saved=self.client.put('/api/lora-triggers',json=dict(row,recommended_prompt=''),headers=self.headers).json['records'][name]
        self.assertEqual(saved['recommended_prompt'],'')

if __name__ == '__main__':
    unittest.main()
