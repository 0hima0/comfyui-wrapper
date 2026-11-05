import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from PIL import Image, PngImagePlugin
from comfyui_wrapper.gallery.gallery_thumbnails import ThumbnailCache
from comfyui_wrapper.gallery.history_store import HistoryStore
from comfyui_wrapper.webui import create_app


class GalleryThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name)
        self.job='a'*32;self.directory=self.root/self.job;self.directory.mkdir()
        self.source=self.directory/'image_0.png'
        metadata=PngImagePlugin.PngInfo();metadata.add_text('workflow','original metadata')
        Image.new('RGBA',(1024,768),(255,0,0,128)).save(self.source,pnginfo=metadata)
        self.store=HistoryStore(self.root/'history.sqlite3')
        self.store.save(self.job,dict(created_at='2026-10-21T00:00:00Z',state='done',artifacts_ready=True,
            images=['image_0.png'],settings=dict(checkpoint='model',seed=0),result=dict(summary_ja='テスト')))
        self.client=create_app(self.root).test_client()

    def tearDown(self):self.temp.cleanup()

    def test_small_thumbnail_keeps_original_and_is_cached(self):
        original=self.source.read_bytes()
        listing=self.client.get('/api/gallery')
        self.assertEqual(listing.headers['Cache-Control'],'no-store')
        item=listing.json['items'][0]
        self.assertNotEqual(item['image_url'],item['thumbnail_url'])
        response=self.client.get(item['thumbnail_url'])
        self.assertEqual(response.status_code,200);self.assertEqual(response.mimetype,'image/jpeg')
        with Image.open(io.BytesIO(response.data)) as preview:
            self.assertEqual(preview.size,(480,360));self.assertEqual(preview.mode,'RGB')
        etag=response.headers['ETag'];self.assertIn('private',response.headers['Cache-Control']);response.close()
        self.assertEqual(self.source.read_bytes(),original)
        with Image.open(self.source) as png:self.assertEqual(png.info['workflow'],'original metadata')
        with patch('comfyui_wrapper.gallery.gallery_thumbnails.Image.open',side_effect=AssertionError('cache should avoid decoding')):
            response=self.client.get(item['thumbnail_url'],headers={'If-None-Match':etag})
            self.assertEqual(response.status_code,304);response.close()
        Image.new('RGB',(400,800),'blue').save(self.source)
        updated=self.client.get('/api/gallery').json['items'][0]
        self.assertNotEqual(updated['thumbnail_url'],item['thumbnail_url'])
        response=self.client.get(updated['thumbnail_url'])
        with Image.open(io.BytesIO(response.data)) as preview:self.assertEqual(preview.size,(240,480))
        response.close()

    def test_parallel_requests_share_atomic_cache(self):
        cache=ThumbnailCache(self.root/'thumbs')
        with ThreadPoolExecutor(max_workers=6) as pool:
            paths=list(pool.map(lambda _:cache.get(self.source),range(6)))
        self.assertEqual(len(set(paths)),1)
        self.assertEqual(len(list((self.root/'thumbs').iterdir())),1)
        with Image.open(paths[0]) as preview:preview.verify()

    def test_unlisted_missing_and_corrupt_images_are_not_served(self):
        self.assertEqual(self.client.get('/gallery/thumbnail/'+self.job+'/reference.png').status_code,404)
        self.assertEqual(self.client.get('/gallery/thumbnail/missing/image_0.png').status_code,404)
        self.source.write_bytes(b'invalid PNG')
        self.assertEqual(self.client.get('/gallery/thumbnail/'+self.job+'/image_0.png').status_code,400)
        self.source.unlink()
        self.assertEqual(self.client.get('/gallery/thumbnail/'+self.job+'/image_0.png').status_code,404)


if __name__=='__main__':unittest.main()
