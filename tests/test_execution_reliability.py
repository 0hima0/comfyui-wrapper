"""Failure, cancellation and persistence tests for execution ownership."""
import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from comfyui_wrapper.infrastructure.job_control import JobControl, JobCancelled
from comfyui_wrapper.integrations.comfy_client import ComfyError
from comfyui_wrapper.webui import create_app


class ExecutionReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app = create_app(self.root)
        self.runner = self.app.extensions['app_services'].runner
        self.history = self.runner.history
        self.settings = dict(threshold=.35, use_wd=False, preserve_people=False, loras=[],
                             execute=True, seed=1, target='animagine', rating='none')
        image = io.BytesIO()
        Image.new('RGB', (8, 8)).save(image, 'PNG')
        self.png = image.getvalue()

    def register(self):
        job = uuid.uuid4().hex
        self.runner.records[job] = dict(state='running', created_at='2026-01-01T00:00:00+00:00',
                                       settings=self.settings)
        self.runner.controls[job] = JobControl()
        self.history.save(job, self.runner.records[job])
        self.runner.busy.acquire()
        return job

    def run_output(self, side_effect):
        job = self.register()
        with ExitStack() as stack:
            stack.enter_context(patch('comfyui_wrapper.generation.generation_jobs.analyze_references',
                return_value=dict(result=dict(positive='blue', negative='text'))))
            stack.enter_context(patch('comfyui_wrapper.analysis.analysis_reuse.fingerprint', return_value='fingerprint'))
            stack.enter_context(patch('comfyui_wrapper.generation.generation_jobs.build_workflow',
                return_value=dict(nodes=[dict(type='KSampler', widgets_values_named={})])))
            stack.enter_context(patch('comfyui_wrapper.generation.generation_jobs.analysis_report',
                return_value=dict(prompt_conflicts={}, wd_threshold=.35, wd_model=None)))
            stack.enter_context(patch('comfyui_wrapper.integrations.comfy_client.to_api', return_value={}))
            stack.enter_context(patch('comfyui_wrapper.integrations.comfy_client.execute',
                return_value=[dict(filename='first.png'), dict(filename='second.png')]))
            stack.enter_context(patch('comfyui_wrapper.integrations.comfy_client.fetch_image', side_effect=side_effect))
            self.runner.run_job(job, [], self.settings)
        return job, self.runner.get_job(job)

    def test_second_download_failure_retains_first_image_and_settings(self):
        with self.assertLogs(self.app.logger, level='ERROR'):
            job, record = self.run_output([self.png, ComfyError('download failed')])
        self.assertEqual(record['state'], 'error')
        self.assertEqual(record['images'], ['image_0.png'])
        report = json.loads((self.root/job/'analysis.json').read_text(encoding='utf-8'))
        self.assertEqual(report['comfy_outputs'], [dict(filename='first.png')])
        gallery = self.app.test_client().get('/api/gallery').json['items']
        self.assertEqual([row['filename'] for row in gallery], ['image_0.png'])
        self.assertNotIn(job, self.runner.records)
        self.assertNotIn(job, self.runner.controls)
        self.assertFalse(self.runner.busy.locked())

    def test_cancellation_retains_first_image(self):
        job, record = self.run_output([self.png, JobCancelled('stopped')])
        self.assertEqual(record['state'], 'cancelled')
        self.assertEqual(record['images'], ['image_0.png'])
        self.assertTrue((self.root/job/'results.zip').is_file())

    def test_success_releases_memory_but_keeps_full_durable_record(self):
        job, record = self.run_output([self.png, self.png])
        self.assertEqual(record['state'], 'done')
        self.assertEqual(len(record['images']), 2)
        self.assertEqual(record['progress']['stage'], 'done')
        self.assertNotIn(job, self.runner.records)
        self.assertNotIn(job, self.runner._progress_saved)
        self.assertFalse(self.runner.cancel(job))

    def test_archive_failures_preserve_images_and_allow_retry(self):
        from comfyui_wrapper.generation import job_archive
        client = self.app.test_client()
        headers = {'X-Requested-With': 'LLMPC'}
        for failure in ('start', 'write', 'verify', 'replace'):
            with self.subTest(failure=failure):
                target = {'start': 'tempfile.mkstemp', 'write': 'zipfile.ZipFile.write',
                          'verify': 'zipfile.ZipFile.testzip', 'replace': 'os.replace'}[failure]
                # Patch only the archive operation; image/report writes must still work.
                original = job_archive.build
                def fail_build(directory):
                    if failure == 'write':
                        write = zipfile.ZipFile.write
                        written = 0
                        def fail_midway(archive, *args, **kwargs):
                            nonlocal written
                            written += 1
                            if written == 2:
                                raise OSError('disk failed after first member')
                            return write(archive, *args, **kwargs)
                        with patch('comfyui_wrapper.generation.job_archive.zipfile.ZipFile.write', autospec=True, side_effect=fail_midway):
                            return original(directory)
                    with patch('comfyui_wrapper.generation.job_archive.' + target, side_effect=OSError('disk failed')):
                        return original(directory)
                with patch.object(job_archive, 'build', side_effect=fail_build), self.assertLogs(self.app.logger, level='ERROR'):
                    job, record = self.run_output([self.png, self.png])
                self.assertEqual(record['state'], 'done')
                self.assertFalse(record['zip_ready'])
                self.assertTrue(record['zip_error'])
                status = client.get('/api/jobs/' + job).json
                self.assertNotIn('results.zip', status['downloads'])
                for name in record['images']:
                    with client.get(status['downloads'][name]) as response:
                        self.assertEqual(response.status_code, 200)
                self.assertEqual(list((self.root/job).glob('*.part')), [])
                with patch.object(job_archive, 'build', side_effect=OSError('retry failed')), self.assertLogs(self.app.logger, level='ERROR'):
                    failed = client.post('/api/jobs/' + job + '/archive', headers=headers).json
                self.assertTrue(failed['zip_error'])
                self.assertNotIn('results.zip', failed['downloads'])
                ready = client.post('/api/jobs/' + job + '/archive', headers=headers).json
                self.assertFalse(ready['zip_error'])
                with client.get(ready['downloads']['results.zip']) as response, zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertIn('image_1.png', archive.namelist())
                # A failed replacement leaves the previous complete ZIP usable.
                previous = (self.root/job/'results.zip').read_bytes()
                with patch.object(job_archive, 'build', side_effect=fail_build), self.assertLogs(self.app.logger, level='ERROR'):
                    failed = client.post('/api/jobs/' + job + '/archive', headers=headers).json
                self.assertIn('results.zip', failed['downloads'])
                self.assertEqual((self.root/job/'results.zip').read_bytes(), previous)

    def test_archive_retry_guards_and_deletion_reservation(self):
        from comfyui_wrapper.generation import job_archive
        from comfyui_wrapper.gallery.gallery_cleanup import DeleteBlocked
        job, _ = self.run_output([self.png, self.png])
        client = self.app.test_client()
        url = '/api/jobs/' + job + '/archive'
        self.assertEqual(client.post(url).status_code, 403)
        self.assertEqual(client.post(url, headers={'X-Requested-With':'LLMPC', 'Origin':'https://other.example'}).status_code, 403)
        original = job_archive.build
        def concurrent(directory):
            with self.assertRaises(DeleteBlocked):
                self.app.extensions['app_services'].cleanup.delete(job)
            self.assertEqual(client.post(url, headers={'X-Requested-With':'LLMPC'}).status_code, 409)
            original(directory)
        with patch.object(job_archive, 'build', side_effect=concurrent):
            self.assertEqual(client.post(url, headers={'X-Requested-With':'LLMPC'}).status_code, 200)
        self.assertNotIn(job, self.runner.records)
        self.assertEqual(client.post('/api/jobs/' + 'f'*32 + '/archive', headers={'X-Requested-With':'LLMPC'}).status_code, 404)

    def test_progress_is_throttled_and_separate_from_settings(self):
        job = self.register()
        self.addCleanup(self.runner.busy.release)
        with patch('comfyui_wrapper.generation.generation_jobs.time.monotonic',
                   side_effect=[10, 10.1, 10.2, 11.1, 11.2]), \
             patch.object(self.history, 'save', wraps=self.history.save) as full_save, \
             patch.object(self.history, 'save_progress', wraps=self.history.save_progress) as save:
            for step in range(4):
                self.runner.report_progress(job, 'generate', 'sampling', step, 28)
            self.runner.report_progress(job, 'save', 'saving')
        self.assertEqual(save.call_count, 3)
        full_save.assert_not_called()
        self.assertEqual(self.runner.get_job(job)['progress']['stage'], 'save')
        self.assertEqual(self.history.get(job)['progress']['stage'], 'save')
        with self.history.connect() as db:
            raw = json.loads(db.execute('SELECT record FROM executions WHERE id=?', (job,)).fetchone()[0])
            self.assertNotIn('progress', raw)
            db.execute('DELETE FROM executions WHERE id=?', (job,))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM execution_progress').fetchone()[0], 0)

    def test_worker_start_failure_releases_admission_and_references(self):
        from comfyui_wrapper.generation.reference_images import ReferenceImage
        image = Image.new('RGB', (8, 8))
        reference = ReferenceImage(1, 'input.png', '', image)
        with patch('comfyui_wrapper.generation.submission.threading.Thread.start', side_effect=RuntimeError('start failed')):
            with self.assertRaisesRegex(RuntimeError, 'start failed'):
                self.runner.submit([reference], self.settings, '1')
        self.assertFalse(self.runner.busy.locked())
        self.assertEqual(self.runner.records, {})
        self.assertEqual(self.runner.controls, {})
        self.assertEqual(self.history.latest()[0]['state'], 'error')
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_busy_rejection_closes_owned_images(self):
        from comfyui_wrapper.generation.reference_images import ReferenceImage
        from comfyui_wrapper.generation.submission import GenerationBusy
        image = Image.new('RGB', (8, 8))
        self.runner.busy.acquire()
        self.addCleanup(self.runner.busy.release)
        with self.assertRaises(GenerationBusy):
            self.runner.submit([ReferenceImage(1, 'input.png', '', image)], self.settings, '1')
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_review_preparation_does_not_block_progress_cancel_or_other_db_writes(self):
        store = self.app.extensions['batch_store']
        batch = 'b' * 32
        job = 'c' * 32
        store.save(batch, dict(state='review', count=1, completed=1, job_ids=[job]))
        folder = self.root/job
        folder.mkdir()
        (folder/'image_0.png').write_bytes(self.png)
        self.history.save(job, dict(created_at='2026-01-01', state='done', images=['image_0.png'],
                                   temporary=True, batch_id=batch, artifacts_ready=True))
        active = self.register()
        self.addCleanup(self.runner.busy.release)
        entered, release = threading.Event(), threading.Event()
        failures = []
        prepare = store._prepare_review
        def slow(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError('preparation timed out')
            return prepare(*args)
        def finalize():
            try:
                store.finalize(batch, [job+'/image_0.png'])
            except Exception as error:
                failures.append(error)
        with patch.object(store, '_prepare_review', side_effect=slow):
            worker = threading.Thread(target=finalize)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.runner.report_progress(active, 'generate', 'sampling', 1, 28)
                self.assertTrue(self.runner.cancel(active))
                self.history.save('other', dict(created_at='2026-01-02', state='done'))
                with self.assertRaisesRegex(ValueError, '別の選別'):
                    store.finalize(batch, [])
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertFalse(self.history.get(job)['temporary'])

    def test_review_rechecks_favorites_before_committing(self):
        store = self.app.extensions['batch_store']
        batch, job = 'd'*32, 'e'*32
        store.save(batch, dict(state='review'))
        folder = self.root/job
        folder.mkdir()
        (folder/'image_0.png').write_bytes(self.png)
        self.history.save(job, dict(created_at='2026-01-01', state='done', images=['image_0.png'],
                                   temporary=True, batch_id=batch, artifacts_ready=True))
        prepare = store._prepare_review
        def favorite_during_copy(*args):
            result = prepare(*args)
            self.history.set_favorite(job, 'image_0.png', True)
            return result
        with patch.object(store, '_prepare_review', side_effect=favorite_during_copy):
            with self.assertRaisesRegex(ValueError, 'お気に入り'):
                store.finalize(batch, [])
        self.assertTrue(self.history.get(job)['temporary'])
        self.assertTrue((folder/'image_0.png').is_file())
        self.assertFalse((self.root/'.batch-finalize'/batch).exists())

    def test_failed_artifact_replacement_preserves_previous_report(self):
        from comfyui_wrapper.analysis.generate import write_json
        target = self.root/'analysis.json'
        write_json(target, {'saved': 1})
        with patch('comfyui_wrapper.infrastructure.artifact_files.os.replace', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                write_json(target, {'saved': 2})
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), {'saved': 1})
        self.assertEqual(list(self.root.glob('*.part')), [])
