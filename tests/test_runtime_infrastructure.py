"""Persistence upgrades and process ownership must fail without losing user data."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from comfyui_wrapper.infrastructure.database import migrate, connection, SCHEMAS
from comfyui_wrapper.gallery.history_store import HistoryStore
from comfyui_wrapper.infrastructure.instance_lock import InstanceLock
from comfyui_wrapper.webui import create_app
from comfyui_wrapper.generation.submission_settings import normalize

ROOT = Path(__file__).resolve().parents[1]


class InfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_legacy_upgrade_preserves_records_and_favorites_and_backs_up_once(self):
        path = self.root/'history.sqlite3'
        with connection(path) as db:
            db.execute(SCHEMAS['history'][0][0])
            db.execute(SCHEMAS['history'][0][2])
            db.execute('INSERT INTO executions VALUES(?,?,?)', ('old','2026-01-01',json.dumps({'created_at':'2026-01-01','state':'done','images':['a.png']})))
            db.execute('INSERT INTO image_favorites VALUES(?,?)', ('old','a.png'))
        store = HistoryStore(path)
        self.assertEqual(store.get('old')['images'], ['a.png'])
        backups = list(self.root.glob('*.pre-v4.*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with connection(backups[0]) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT * FROM image_favorites').fetchall(), [('old','a.png')])
        HistoryStore(path)
        self.assertEqual(len(list(self.root.glob('*.pre-v4.*.sqlite3'))), 1)
        with store.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], len(SCHEMAS['history']))
            self.assertEqual(db.execute('SELECT * FROM image_favorites').fetchall(), [('old','a.png')])

    def test_failed_upgrade_rolls_back_schema_and_version(self):
        path = self.root/'failed.sqlite3'
        with connection(path) as db:
            db.execute('CREATE TABLE original (value TEXT)')
            db.execute("INSERT INTO original VALUES('keep')")
        with patch.dict(SCHEMAS, failing=(("CREATE TABLE partial (id INTEGER)", "INVALID SQL"),)):
            with self.assertRaises(sqlite3.OperationalError):
                migrate(path, 'failing')
        with connection(path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchone())
            self.assertEqual(db.execute('SELECT value FROM original').fetchone()[0], 'keep')

    def test_newer_database_is_rejected_without_changes(self):
        path = self.root/'newer.sqlite3'
        with connection(path) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):
            HistoryStore(path)
        with connection(path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)
            self.assertEqual(db.execute('SELECT name FROM sqlite_master').fetchall(), [])
        self.assertEqual(list(self.root.glob('*.pre-v4.*')), [])

    def test_backup_failure_does_not_start_upgrade(self):
        path = self.root/'backup.sqlite3'
        with connection(path) as db:
            db.execute('CREATE TABLE original (id INTEGER)')
        with patch('comfyui_wrapper.infrastructure.database.connection', wraps=connection) as connect:
            connect.side_effect=lambda p, **kw: (_ for _ in ()).throw(PermissionError('backup blocked')) if '.pre-v4.' in str(p) else connection(p, **kw)
            with self.assertRaises(PermissionError):
                migrate(path, 'history')
        with connection(path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='executions'").fetchone())

    def child_lock(self, path):
        code = "from comfyui_wrapper.infrastructure.instance_lock import InstanceLock; import sys; lock=InstanceLock(sys.argv[1]); lock.__enter__(); lock.__exit__()"
        env = dict(os.environ, PYTHONPATH=str(ROOT/'src'))
        return subprocess.run([sys.executable,'-c',code,str(path)],env=env,cwd=self.root,capture_output=True,timeout=15)

    def test_process_lock_rejects_same_root_and_releases_after_exit(self):
        with InstanceLock(self.root):
            self.assertNotEqual(self.child_lock(self.root).returncode, 0)
            self.assertEqual(self.child_lock(self.root/'other').returncode, 0)
        self.assertEqual(self.child_lock(self.root).returncode, 0)
        # The kernel releases the lock even when the child skips __exit__.
        code="from comfyui_wrapper.infrastructure.instance_lock import InstanceLock; import os,sys; lock=InstanceLock(sys.argv[1]); lock.__enter__(); os._exit(0)"
        result=subprocess.run([sys.executable,'-c',code,str(self.root)],env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),capture_output=True,timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.child_lock(self.root).returncode, 0)

    def test_restart_adds_end_time_without_resubmitting_to_comfy(self):
        store = HistoryStore(self.root/'history.sqlite3')
        store.save('old', {'created_at':'2026-01-01','state':'running'})
        with patch('urllib.request.urlopen') as network:
            app = create_app(self.root)
        self.assertTrue(app.extensions['app_services'].history.get('old')['finished_at'])
        network.assert_not_called()

    def test_preflight_and_submission_share_cross_field_validation(self):
        client = create_app(self.root).test_client()
        headers = {'X-Requested-With':'LLMPC'}
        fields = dict(target='animagine',checkpoint='AnimagineXL_v31.safetensors',rating='auto',use_wd=False,instruction='a park')
        checked=client.post('/api/preflight',json={'fields':fields,'reference_ids':[1]},headers=headers)
        from tests.support import image_upload
        form={k:v for k,v in fields.items() if k!='use_wd'}
        form['image']=image_upload()
        submitted=client.post('/api/jobs',data=form,headers=headers)
        self.assertEqual(checked.status_code,400)
        self.assertEqual(submitted.status_code,400)
        self.assertEqual(checked.json['error'],submitted.json['error'])

    def test_preflight_honors_restored_generation_and_explicit_override(self):
        app = create_app(self.root)
        data = dict(fields=dict(target='animagine',checkpoint='AnimagineXL_v31.safetensors',cfg='6'),reference_ids=[1],restored_generation=dict(steps=42,cfg=9))
        with patch('comfyui_wrapper.system.preflight.check',return_value={'ok':True,'checks':[]}) as check:
            response=app.test_client().post('/api/preflight',json=data,headers={'X-Requested-With':'LLMPC'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(check.call_args.args[0]['generation_effective']['steps'],42)
        self.assertEqual(check.call_args.args[0]['generation_effective']['cfg'],6)

    def test_batch_variants_retain_normalized_settings_and_only_change_selected_values(self):
        from comfyui_wrapper.generation.batch_generation import variants
        app = create_app(self.root)
        services=app.extensions['app_services']
        form=dict(target='animagine',checkpoint='AnimagineXL_v31.safetensors',execute='on',use_wd='on',seed='123',threshold='.35')
        settings,_,_=normalize(form,services.runtime,services.catalog,1,check_wd=False)
        planned=variants(dict(count=3,ranges=[dict(field='threshold',start=.2,end=.4)]),settings)
        self.assertEqual([row['threshold'] for row in planned],[.2,.3,.4])
        self.assertTrue(all(row['seed']==123 and row['generation_effective']==settings['generation_effective'] for row in planned))
        self.assertEqual(settings['threshold'],.35)

    def test_terminal_db_failure_releases_generation_lock_and_controls(self):
        from comfyui_wrapper.infrastructure.job_control import JobControl, local
        app = create_app(self.root)
        runner = app.extensions['app_services'].runner
        runner.busy.acquire()
        runner.controls['old'] = JobControl()
        runner.records['old'] = dict(state='running',created_at='2026-01-01')
        with patch('comfyui_wrapper.generation.generation_jobs.analyze_references',side_effect=ValueError('analysis failed')), patch.object(runner.history,'save',side_effect=sqlite3.OperationalError('disk full')), self.assertLogs(app.logger,level='ERROR'):
            with self.assertRaises(sqlite3.OperationalError):
                runner.run_job('old',[],{'threshold':.35})
        self.assertFalse(runner.busy.locked())
        self.assertNotIn('old',runner.controls)
        self.assertIsNone(local.control)
        self.assertEqual(runner.records['old']['state'],'error')
