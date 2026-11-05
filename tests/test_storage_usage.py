import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from comfyui_wrapper.gallery.history_store import HistoryStore
from comfyui_wrapper.gallery.storage_usage import StorageUsage
from comfyui_wrapper.webui import create_app


class StorageUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.history=HistoryStore(self.root/'history.sqlite3')
        self.usage=StorageUsage(self.root,self.history)

    def job(self,key,temporary=False):
        job_id=f'{key:032x}'
        self.history.save(job_id,dict(created_at='2026-10-22T00:00:00+00:00',state='done',
            artifacts_ready=True,images=['image_0.png','image_1.png'],temporary=temporary))
        directory=self.root/job_id;directory.mkdir()
        return job_id,directory

    def write(self,path,size):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x'*size)

    def test_partition_counts_every_file_once_and_protects_whole_execution(self):
        normal,a=self.job(1);protected,b=self.job(2);temporary,c=self.job(3,True)
        self.write(a/'image_0.png',10);self.write(a/'references'/'ref.png',20)
        self.write(b/'image_0.png',30);self.write(b/'image_1.png',40);self.write(b/'results.zip',50)
        self.history.set_favorite(protected,'image_0.png',True)
        self.write(c/'image_0.png',60)
        self.write(self.root/('f'*32)/'orphan.png',70)
        self.write(self.root/'.gallery-thumbnails'/'thumb.jpg',80)
        self.write(self.root/'lora-samples'/'sample.png',90)
        self.write(self.root/'settings-presets.sqlite3',100)
        data=self.usage.get()
        self.assertEqual(data['categories']['normal'],dict(bytes=30,files=2,executions=1))
        self.assertEqual(data['categories']['protected'],dict(bytes=120,files=3,executions=1))
        self.assertEqual(data['categories']['temporary'],dict(bytes=60,files=1,executions=1))
        expected=sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        self.assertEqual(data['total']['bytes'],expected)
        self.assertEqual(data['categories']['other']['bytes'],expected-210)
        self.assertEqual(data['total']['files'],11)
        self.assertFalse(data['partial'])
        self.assertGreater(data['disk']['total'],0)

    def test_partial_scan_and_unavailable_disk_do_not_claim_complete_measurement(self):
        _,directory=self.job(1);self.write(directory/'image_0.png',10)
        actual_scandir=__import__('os').scandir
        def scan(path):
            if Path(path)==directory:raise PermissionError('denied')
            return actual_scandir(path)
        with patch('comfyui_wrapper.gallery.storage_usage.os.scandir',side_effect=scan),patch('comfyui_wrapper.gallery.storage_usage.shutil.disk_usage',side_effect=OSError('unavailable')):
            data=self.usage.get()
        self.assertTrue(data['partial']);self.assertGreaterEqual(data['unreadable_entries'],2)
        self.assertIsNone(data['disk'])
        self.assertEqual(data['categories']['normal']['bytes'],0)

    def test_directory_links_are_not_followed(self):
        outside_temp=tempfile.TemporaryDirectory(dir=self.root.parent)
        self.addCleanup(outside_temp.cleanup)
        outside=Path(outside_temp.name)
        (outside/'private.bin').write_bytes(b'x'*1000)
        link=self.root/'link'
        try:link.symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('Creating directory links is not permitted on this host')
        self.addCleanup(link.unlink)
        data=self.usage.get()
        self.assertEqual(data['skipped_links'],1)
        self.assertEqual(data['total']['bytes'],(self.root/'history.sqlite3').stat().st_size)

    def test_cache_force_refresh_invalidation_and_copy_isolation(self):
        with patch.object(self.usage,'scan',return_value={'total':{'bytes':1}}) as scan:
            first=self.usage.get();first['total']['bytes']=99
            self.assertEqual(self.usage.get()['total']['bytes'],1);self.assertEqual(scan.call_count,1)
            self.usage.get(force=True);self.assertEqual(scan.call_count,2)
            self.usage.invalidate();self.usage.get();self.assertEqual(scan.call_count,3)

    def test_mutation_during_measurement_does_not_cache_outdated_result(self):
        def measure():self.usage.invalidate();return {'total':{'bytes':1}}
        with patch.object(self.usage,'scan',side_effect=measure) as scan:
            self.usage.get();self.usage.get();self.assertEqual(scan.call_count,2)

    def test_cache_expires(self):
        self.usage.ttl=5
        with patch('comfyui_wrapper.gallery.storage_usage.time.monotonic',side_effect=[10,11,12,20,21]),patch.object(self.usage,'scan',return_value={}) as scan:
            self.usage.get();self.usage.get();self.usage.get();self.assertEqual(scan.call_count,2)

    def test_endpoint_is_separate_from_gallery_loading_and_validates_refresh(self):
        app=create_app(self.root/'app');client=app.test_client()
        usage=app.extensions['storage_usage']
        with patch.object(usage,'scan',wraps=usage.scan) as scan:
            for path in ('/gallery','/batches'):
                response=client.get(path);self.assertEqual(response.status_code,200)
                self.assertNotIn('id="storage-total"',response.get_data(as_text=True))
            response=client.get('/storage');self.assertEqual(response.status_code,200)
            self.assertIn('id="storage-total"',response.get_data(as_text=True))
            client.get('/api/gallery');scan.assert_not_called()
            response=client.get('/api/storage-usage');self.assertEqual(response.status_code,200)
            self.assertIn('no-store',response.headers['Cache-Control'])
            client.get('/api/storage-usage');self.assertEqual(scan.call_count,1)
            client.get('/api/storage-usage?refresh=1');self.assertEqual(scan.call_count,2)
        self.assertEqual(client.get('/api/storage-usage?refresh=bad').status_code,400)
        with patch.object(usage,'get',side_effect=OSError('failed')),self.assertLogs(app.logger,level='ERROR'):
            self.assertEqual(client.get('/api/storage-usage').status_code,503)

    def test_favorite_changes_and_deletion_invalidate_capacity_cache(self):
        root=self.root/'app';app=create_app(root);client=app.test_client()
        store=HistoryStore(root/'history.sqlite3');job_id='a'*32
        store.save(job_id,dict(created_at='2026-10-22T00:00:00+00:00',state='done',artifacts_ready=True,images=['image_0.png']))
        self.write(root/job_id/'image_0.png',20)
        headers={'X-Requested-With':'LLMPC'}
        self.assertEqual(client.get('/api/storage-usage').json['categories']['normal']['bytes'],20)
        response=client.put('/api/gallery/'+job_id+'/image_0.png/favorite',json={'favorite':True},headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(client.get('/api/storage-usage').json['categories']['protected']['bytes'],20)
        self.assertEqual(client.delete('/api/gallery/'+job_id,headers=headers).status_code,409)
        client.put('/api/gallery/'+job_id+'/image_0.png/favorite',json={'favorite':False},headers=headers)
        self.assertEqual(client.get('/api/storage-usage').json['categories']['normal']['bytes'],20)
        self.assertEqual(client.delete('/api/gallery/'+job_id,headers=headers).status_code,200)
        self.assertEqual(client.get('/api/storage-usage').json['categories']['normal']['bytes'],0)
