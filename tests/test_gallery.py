from tests.support import GalleryFixture
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from comfyui_wrapper.gallery.history_store import HistoryStore
from comfyui_wrapper.webui import create_app


class GalleryTests(GalleryFixture, unittest.TestCase):
    def test_gallery_browses_beyond_twenty_and_paginates(self):
        for i in range(27):self.save(i)
        first=self.client.get('/api/gallery').json
        self.assertEqual(len(first['items']),24)
        self.assertEqual(first['items'][0]['seed'],26)
        self.assertTrue(first['has_more']);self.assertEqual(first['next_offset'],24)
        second=self.client.get('/api/gallery?offset=24').json
        self.assertEqual([x['seed'] for x in second['items']],[2,1,0])
        self.assertFalse(second['has_more'])
        self.assertEqual(len(self.client.get('/api/history').json['items']),20)
        self.assertEqual(self.client.get('/gallery').status_code,200)

    def test_86_outputs_are_paged_without_duplicates(self):
        for i in range(86):self.save(i)
        seen=[];offset=0
        while True:
            page=self.client.get('/api/gallery?offset='+str(offset)).json
            self.assertLessEqual(len(page['items']),24)
            seen.extend((item['job_id'],item['filename']) for item in page['items'])
            if not page['has_more']:break
            self.assertGreater(page['next_offset'],offset);offset=page['next_offset']
        self.assertEqual(len(seen),86);self.assertEqual(len(set(seen)),86)

    def test_card_urls_restore_exact_execution_and_serve_inline_image(self):
        job=self.save(4,output_files=[dict(webui_filename='image_0.png',comfy_filename='LLMPC_004.png')])
        item=self.client.get('/api/gallery').json['items'][0]
        self.assertEqual(item['comfy_filename'],'LLMPC_004.png')
        self.assertEqual(item['restore_url'],'/?restore='+job)
        response=self.client.get(item['image_url'])
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.headers['Content-Disposition'].startswith('inline'))
        response.close()
        restored=self.client.get('/api/history/'+job+'/restore').json
        self.assertEqual(restored['fields']['seed'],4)
        self.assertEqual(restored['fields']['instruction'],'公園で二人')
        self.assertEqual(restored['generation_settings'],dict(steps=28,cfg=5))
        self.assertEqual(restored['loras'][0]['scope'],'image:1')
        self.assertEqual(restored['reference_images'][0]['filename'],'person.png')
        response=self.client.get(item['settings_url']);self.assertEqual(response.status_code,200);response.close()

    def test_no_source_images_or_missing_files_and_bad_offsets(self):
        self.save(0,images=[])
        job=self.save(1);(self.root/job/'image_0.png').unlink()
        self.save(2,artifacts_ready=False)
        self.save(3,state='running')
        self.save(4,images=['../outside.png'])
        self.assertEqual(self.client.get('/api/gallery').json['items'],[])
        for offset in ('-1','bad','1000001'):
            self.assertEqual(self.client.get('/api/gallery?offset='+offset).status_code,400)
        self.assertEqual(self.client.get('/api/gallery?offset=100').json['items'],[])


if __name__=='__main__':unittest.main()
