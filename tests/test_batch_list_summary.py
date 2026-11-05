"""Batch list renders useful metadata without loading full-size images."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from comfyui_wrapper.webui import create_app

class BatchListSummaryTests(unittest.TestCase):
    def test_summary_and_empty_preview(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            app=create_app(folder)
            services=app.extensions['app_services']
            batch=dict(batch_id='a'*32,state='review',created_at='2026-10-24T00:00:00+00:00',
                       completed=2,count=3,message='ready',
                       plan=dict(ranges=[dict(field='strength_model',lora=0,start=.3,end=.9)]))
            records=[dict(job_id='b'*32,images=['image_0.png'],settings=dict(checkpoint='sample-model.safetensors'))]
            with patch.object(services.batches,'all',return_value=[batch]),patch.object(services.history,'image_page',return_value=(records,False)) as read:
                response=app.test_client().get('/batches')
                self.assertEqual(response.status_code,200)
                page=response.get_data(as_text=True)
                self.assertIn('sample-model.safetensors',page)
                self.assertIn('LoRA 1 MODEL強度',page)
                self.assertIn('0.3 → 0.9',page)
                self.assertIn('/gallery/thumbnail/'+('b'*32)+'/image_0.png',page)
                read.assert_called_once_with(limit=3,batch_id='a'*32)
            batch['checkpoint']='pending-model.safetensors'
            with patch.object(services.batches,'all',return_value=[batch]),patch.object(services.history,'image_page',return_value=([],False)):
                page=app.test_client().get('/batches').get_data(as_text=True)
                self.assertIn('pending-model.safetensors',page)
                self.assertIn('完成した画像はまだありません',page)
