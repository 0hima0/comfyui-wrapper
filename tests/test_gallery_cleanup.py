import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from tests.support import GalleryFixture


class CleanupTests(GalleryFixture, unittest.TestCase):

    def delete(self,job,**headers):
        return self.client.delete('/api/gallery/'+job,headers={'X-Requested-With':'LLMPC',**headers})

    def favorite(self,job):
        self.client.put(f'/api/gallery/{job}/image_0.png/favorite',json={'favorite':True},headers={'X-Requested-With':'LLMPC'})

    def test_delete_removes_images_settings_artifacts_cache_and_memory(self):
        job=self.save(1)
        for name in ('analysis.json','workflow.json','results.zip','positive.txt'):
            (self.root/job/name).write_text('test',encoding='utf-8')
        ref=self.root/job/'references';ref.mkdir();(ref/'input.png').write_bytes(b'test')
        item=self.client.get('/api/gallery').json['items'][0]
        response=self.client.get(item['thumbnail_url']);response.close()
        self.assertEqual(len(list((self.root/'.gallery-thumbnails').iterdir())),1)
        self.client.application.extensions['image_jobs'][job]=self.store.get(job)
        self.assertEqual(self.delete(job).status_code,200)
        self.assertIsNone(self.store.get(job));self.assertFalse((self.root/job).exists())
        self.assertNotIn(job,self.client.application.extensions['image_jobs'])
        self.assertEqual(list((self.root/'.gallery-thumbnails').iterdir()),[])
        for url in (item['image_url'],item['settings_url'],item['restore_url'].replace('/?restore=','/api/history/')+'/restore','/api/jobs/'+job):
            self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.delete(job).status_code,404)

    def test_favorite_protects_entire_execution_even_with_stale_ui(self):
        job=self.save(1,images=['image_0.png','image_1.png'])
        self.favorite(job)
        items=self.client.get('/api/gallery').json['items']
        self.assertTrue(all(i['protected'] for i in items))
        self.assertEqual(self.delete(job).status_code,409)
        self.assertTrue((self.root/job/'image_1.png').exists())

    def test_expiry_exact_boundary_finished_time_favorites_and_running(self):
        now=datetime(2026,10,22,12,tzinfo=timezone.utc)
        cutoff=now-timedelta(days=10)
        jobs=[]
        for i,finished in enumerate((cutoff,cutoff+timedelta(seconds=1),cutoff-timedelta(days=1))):
            jobs.append(self.save(i,created_at=(cutoff-timedelta(days=5)).isoformat(),finished_at=finished.isoformat()))
        self.favorite(jobs[2])
        running=self.save(4,state='running',created_at=(cutoff-timedelta(days=2)).isoformat())
        invalid=self.save(5,created_at='bad date')
        legacy=self.save(6,created_at=cutoff.isoformat())
        cleanup=self.client.application.extensions['gallery_cleanup']
        self.assertEqual(cleanup.sweep(now),2)
        for job in (jobs[0],legacy):self.assertIsNone(self.store.get(job))
        for job in (jobs[1],jobs[2],running,invalid):self.assertIsNotNone(self.store.get(job))
        self.assertEqual(cleanup.sweep(now),0)

    def test_delete_guards_and_failed_move_keep_history(self):
        job=self.save(1)
        self.assertEqual(self.client.delete('/api/gallery/'+job).status_code,403)
        self.assertEqual(self.delete(job,Origin='http://other.example').status_code,403)
        self.assertEqual(self.delete('not-a-job').status_code,404)
        with patch('pathlib.Path.rename',side_effect=PermissionError('mock permission failure')):
            self.assertEqual(self.delete(job).status_code,500)
        self.assertIsNotNone(self.store.get(job));self.assertTrue((self.root/job).is_dir())
        self.save(1,state='running');self.assertEqual(self.delete(job).status_code,409)

    def test_configured_retention_boundary_and_protected_data(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        cutoff=now-timedelta(days=30)
        expired=self.save(1,finished_at=cutoff.isoformat())
        recent=self.save(2,finished_at=(cutoff+timedelta(seconds=1)).isoformat())
        favorite=self.save(3,finished_at=(cutoff-timedelta(days=1)).isoformat());self.favorite(favorite)
        temporary=self.save(4,temporary=True,finished_at=cutoff.isoformat())
        running=self.save(5,state='running',created_at=cutoff.isoformat())
        from comfyui_wrapper.gallery.gallery_cleanup import ExecutionCleanup
        cleanup=ExecutionCleanup(self.store,self.root,self.client.application.extensions['app_services'].runner.lock,{},retention_days=30)
        self.assertEqual(cleanup.sweep(now),1)
        self.assertIsNone(self.store.get(expired))
        for job in (recent,favorite,temporary,running):
            self.assertIsNotNone(self.store.get(job));self.assertTrue((self.root/job).exists())

    def test_zero_disables_expiry_but_allows_manual_delete_and_staging_recovery(self):
        from comfyui_wrapper.gallery.gallery_cleanup import ExecutionCleanup
        cleanup=ExecutionCleanup(self.store,self.root,self.client.application.extensions['app_services'].runner.lock,{},retention_days=0)
        old=self.save(1,created_at='2000-01-01T00:00:00+00:00')
        protected=self.save(2);self.favorite(protected)
        staging=self.root/'.deleting';staging.mkdir();(self.root/protected).rename(staging/protected)
        self.assertEqual(cleanup.sweep(datetime(2030,1,1,tzinfo=timezone.utc)),0)
        self.assertIsNotNone(self.store.get(old));self.assertTrue((self.root/old).exists())
        self.assertTrue((self.root/protected).exists())
        self.assertTrue(cleanup.delete(old))

    def test_cleanup_thread_runs_immediately_and_stops(self):
        import threading
        cleanup=self.client.application.extensions['gallery_cleanup'];called=threading.Event()
        with patch.object(cleanup,'sweep',side_effect=lambda:called.set()):
            cleanup.start();self.assertTrue(called.wait(2))
            worker=cleanup.worker;cleanup.start();self.assertIs(cleanup.worker,worker)
            cleanup.stop.set();worker.join(2);self.assertFalse(worker.is_alive())

    def test_interrupted_deletion_restores_protected_execution(self):
        job=self.save(1);self.favorite(job)
        staging=self.root/'.deleting';staging.mkdir()
        (self.root/job).rename(staging/job)
        cleanup=self.client.application.extensions['gallery_cleanup']
        self.assertEqual(cleanup.sweep(datetime(2030,1,1,tzinfo=timezone.utc)),0)
        self.assertTrue((self.root/job/'image_0.png').is_file())
        self.assertIsNotNone(self.store.get(job))
