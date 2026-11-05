import unittest
from unittest.mock import patch
from tests.support import GalleryFixture


class BulkDeleteTests(GalleryFixture, unittest.TestCase):

    def delete(self,ids,**headers):
        return self.client.post('/api/gallery/bulk-delete',json={'job_ids':ids},headers={'X-Requested-With':'LLMPC',**headers})

    def test_bulk_deletes_unique_executions_with_images_and_settings(self):
        first=self.save(1,images=['image_0.png','image_1.png']);second=self.save(2)
        for job in (first,second):(self.root/job/'workflow.json').write_text('{}')
        response=self.delete([first,second,first])
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json,{'deleted':[first,second],'skipped':[]})
        for job in (first,second):
            self.assertIsNone(self.store.get(job));self.assertFalse((self.root/job).exists())
        self.assertEqual(self.client.get('/api/gallery').json['items'],[])

    def test_protected_stale_selection_running_and_temporary_are_skipped(self):
        first=self.save(1);favorite=self.save(2,images=['image_0.png','image_1.png'])
        self.client.get('/api/gallery')
        self.store.set_favorite(favorite,'image_0.png',True)
        running=self.save(3,state='running');temporary=self.save(4,temporary=True,batch_id='b'*32)
        missing='f'*32
        response=self.delete([first,favorite,running,temporary,missing]).json
        self.assertEqual(response['deleted'],[first])
        self.assertEqual([v['job_id'] for v in response['skipped']],[favorite,running,temporary,missing])
        for job in (favorite,running,temporary):
            self.assertIsNotNone(self.store.get(job));self.assertTrue((self.root/job/'image_0.png').is_file())
        self.assertIn('お気に入り',response['skipped'][0]['error'])

    def test_bad_requests_are_rejected_before_any_deletion(self):
        job=self.save(1)
        for ids in ([],None,{},[job,'../outside'],[job,1],[job]*501):
            self.assertEqual(self.delete(ids).status_code,400)
            self.assertIsNotNone(self.store.get(job))
        self.assertEqual(self.client.post('/api/gallery/bulk-delete',json={'job_ids':[job]}).status_code,403)
        self.assertEqual(self.delete([job],Origin='http://other.test').status_code,403)

    def test_file_error_does_not_delete_failed_execution_or_prevent_other_deletions(self):
        failed=self.save(1);good=self.save(2)
        cleanup=self.client.application.extensions['gallery_cleanup'];original=cleanup.delete
        def remove(job):
            if job==failed:raise PermissionError('mock permission failure')
            return original(job)
        with patch.object(cleanup,'delete',side_effect=remove),self.assertLogs(self.client.application.logger,level='ERROR'):
            response=self.delete([failed,good]).json
        self.assertEqual(response['deleted'],[good]);self.assertEqual(response['skipped'][0]['job_id'],failed)
        self.assertTrue((self.root/failed/'image_0.png').is_file());self.assertIsNotNone(self.store.get(failed))
