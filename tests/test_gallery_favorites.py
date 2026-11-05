import unittest
from tests.support import GalleryFixture
from comfyui_wrapper.webui import create_app


class GalleryFavoriteTests(GalleryFixture, unittest.TestCase):
    def favorite(self,job,name='image_0.png',value=True,**kwargs):
        return self.client.put(f'/api/gallery/{job}/{name}/favorite',json={'favorite':value},
                               headers={'X-Requested-With':'LLMPC',**kwargs})

    def test_individual_images_persist_and_execution_updates_keep_favorites(self):
        job=self.save(1,images=['image_0.png','image_1.png'])
        self.assertEqual(self.favorite(job).json,{'favorite':True})
        self.assertEqual(self.favorite(job).status_code,200)
        self.save(1,images=['image_0.png','image_1.png'])
        self.client=create_app(self.root).test_client()
        all_items=self.client.get('/api/gallery').json['items']
        self.assertEqual([i['favorite'] for i in all_items],[True,False])
        selected=self.client.get('/api/gallery?favorites=1').json['items']
        self.assertEqual([i['filename'] for i in selected],['image_0.png'])
        self.assertEqual(self.favorite(job,value=False).json,{'favorite':False})
        self.assertEqual(self.client.get('/api/gallery?favorites=1').json['items'],[])

    def test_filter_queries_all_history_and_paginates_matches(self):
        for i in range(56):
            job=self.save(i)
            if i<27:self.favorite(job)
        first=self.client.get('/api/gallery?favorites=1').json
        self.assertEqual([i['seed'] for i in first['items']],list(range(26,2,-1)))
        self.assertTrue(first['has_more'])
        second=self.client.get('/api/gallery?favorites=1&offset='+str(first['next_offset'])).json
        self.assertEqual([i['seed'] for i in second['items']],[2,1,0])
        self.assertFalse(second['has_more'])

    def test_invalid_requests_and_unavailable_images_are_rejected(self):
        job=self.save(1)
        url=f'/api/gallery/{job}/image_0.png/favorite'
        self.assertEqual(self.client.put(url,json={'favorite':True}).status_code,403)
        self.assertEqual(self.favorite(job,Origin='http://other.example').status_code,403)
        for value in ('true',1,None,[],{}):
            self.assertEqual(self.favorite(job,value=value).status_code,400)
        self.assertEqual(self.favorite(job,name='not-recorded.png').status_code,404)
        self.assertEqual(self.favorite('unknown').status_code,404)
        (self.root/job/'image_0.png').unlink()
        self.assertEqual(self.favorite(job).status_code,404)
        for state in ({'state':'running'},{'artifacts_ready':False}):
            self.save(1,**state)
            self.assertEqual(self.favorite(job).status_code,404)
        self.assertEqual(self.client.get('/api/gallery?favorites=invalid').status_code,400)
