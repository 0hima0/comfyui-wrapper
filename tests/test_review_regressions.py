"""Regression coverage for bounded history scans, compact metadata and receipts."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.gallery.history_store import HistoryStore


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=create_app(self.root)
        self.services=self.app.extensions['app_services']
        self.client=self.app.test_client()

    def test_startup_decodes_running_records_only_and_uses_index(self):
        store=self.services.history
        with store.connect() as db:
            db.executemany('INSERT INTO executions VALUES(?,?,?)',[(str(i),'2026-10-01',json.dumps(dict(created_at='2026-10-01',state='running' if i<2 else 'done'))) for i in range(1000)])
            plan=db.execute("EXPLAIN QUERY PLAN SELECT id,record FROM executions WHERE json_extract(record,'$.state')='running'").fetchall()
        self.assertIn('executions_running',str(plan))
        with patch('comfyui_wrapper.gallery.history_store.json.loads',wraps=json.loads) as decode:
            HistoryStore(store.path)
        self.assertEqual(decode.call_count,2)

    def test_cleanup_sql_filters_expiry_and_uses_expression_index(self):
        store=self.services.history;cleanup=self.services.cleanup
        now=datetime(2026,10,29,tzinfo=timezone.utc)
        for i,days in enumerate((30,1,1,1)):
            store.save(f'{i:032x}',dict(created_at=(now-timedelta(days=days)).isoformat(),state='done',artifacts_ready=True,images=['image_0.png']))
        with patch.object(cleanup,'delete',return_value=True) as delete:
            self.assertEqual(cleanup.sweep(now),1)
        self.assertEqual(delete.call_args.args[0],'0'*32)
        with store.connect() as db:
            plan=db.execute("EXPLAIN QUERY PLAN SELECT id FROM executions WHERE julianday(COALESCE(NULLIF(json_extract(record,'$.finished_at'),''),json_extract(record,'$.created_at'))) <= julianday(?)",(now.isoformat(),)).fetchall()
        self.assertIn('executions_finished',str(plan))

    def test_gallery_annotations_are_one_query_per_page(self):
        from PIL import Image
        store=self.services.history
        for i in range(4):
            job=f'{i:032x}';folder=self.root/job;folder.mkdir()
            Image.new('RGB',(8,8)).save(folder/'image_0.png')
            store.save(job,dict(created_at='2026-10-01',state='done',artifacts_ready=True,images=['image_0.png']))
            store.annotate(job,'image_0.png','memo '+str(i),['tag'])
        with patch.object(store,'annotations_many',wraps=store.annotations_many) as many,patch.object(store,'annotations',side_effect=AssertionError('per-job query')):
            response=self.client.get('/api/gallery?label=tag')
        self.assertEqual(len(response.json['items']),4)
        self.assertEqual(many.call_count,1)
        self.assertEqual({item['annotation']['note'] for item in response.json['items']},{'memo '+str(i) for i in range(4)})

    def test_lora_summary_transfer_is_independent_of_long_fields_and_legacy_api_remains(self):
        store=self.services.lora_store
        with store.connect() as db:
            db.executemany('INSERT INTO loras VALUES(?,?,?,?,?,?)',[(f'lora/{i}','','','short','["tag"]','short') for i in range(1000)])
        small=self.client.get('/api/lora-triggers?summary=1').data
        with store.connect() as db:db.execute('UPDATE loras SET note=?,recommended_prompt=?',('x'*8000,'y'*8000))
        self.assertEqual(small,self.client.get('/api/lora-triggers?summary=1').data)
        detail=self.client.get('/api/lora-triggers?name=lora/1').json
        self.assertEqual(list(detail['records']),['lora/1'])
        self.assertEqual(len(detail['records']['lora/1']['note']),8000)
        self.assertEqual(len(self.client.get('/api/lora-triggers').json['records']),1000)
        response=self.client.put('/api/lora-triggers?summary=1',headers={'X-Requested-With':'LLMPC'},json=dict(name='lora/1',trigger='token',note='new'))
        self.assertEqual(response.json['record']['recommended_prompt'],'y'*8000)
        self.assertNotIn('note',response.json['records']['lora/1'])

    def test_same_receipt_returns_existing_job_before_and_after_restart(self):
        key='e'*32;headers={'X-Requested-With':'LLMPC','X-Request-ID':key}
        with patch('comfyui_wrapper.generation.submission.threading.Thread') as thread:
            response=self.client.post('/api/jobs',data=dict(target='animagine',checkpoint='example.safetensors',instruction='park'),headers=headers)
            self.assertEqual(response.status_code,202)
            self.assertEqual(response.json,dict(job_id=key))
            self.assertEqual(self.client.post('/api/jobs',headers=headers).json,response.json)
            self.assertEqual(thread.call_count,1)
        self.services.runner.busy.release()
        fresh=create_app(self.root).test_client()
        with patch('comfyui_wrapper.generation.submission.threading.Thread') as thread:
            self.assertEqual(fresh.post('/api/jobs',headers=headers).json,dict(job_id=key))
            thread.assert_not_called()

