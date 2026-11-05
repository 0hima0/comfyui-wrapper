import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from comfyui_wrapper.settings.app_config import load_config
from comfyui_wrapper.webui import create_app, parse_args
from comfyui_wrapper.prompts.prompt_rules import filter_candidates, merge_prompts


class SettingsTests(unittest.TestCase):
    def test_gallery_retention_config_defaults_values_and_invalid_types(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'synthetic-retention.json'
            path.write_text('{}',encoding='utf-8')
            self.assertEqual(load_config(path)['gallery_retention_days'],10)
            for days in (0,1,30,36500):
                path.write_text(json.dumps({'gallery_retention_days':days}),encoding='utf-8')
                args=parse_args(['--config',str(path)])
                self.assertEqual(args.gallery_retention_days,days)
                app=create_app(Path(folder)/str(days),gallery_retention_days=args.gallery_retention_days)
                self.assertEqual(app.extensions['gallery_cleanup'].retention_days,days)
                for page in ('/','/gallery'):
                    content=app.test_client().get(page).get_data(as_text=True)
                    self.assertIn(f'{days}日' if days else '自動削除は無効',content)
            for invalid in (-1,36501,True,False,1.5,'30',None):
                path.write_text(json.dumps({'gallery_retention_days':invalid}),encoding='utf-8')
                with self.subTest(value=invalid),self.assertRaises(ValueError):load_config(path)

    def test_config_file_and_cli_override(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent.resolve()) as folder:
            path=Path(folder)/'config.json'
            path.write_text(json.dumps({'model':'vision:local','port':7870,'output_dir':'saved','wd_dir':None}),encoding='utf-8')
            config=load_config(path)
            self.assertEqual(config['output_dir'],Path(folder)/'saved')
            args=parse_args(['--config',str(path),'--port','7871'])
            self.assertEqual(args.port,7871)
            self.assertEqual(args.model,'vision:local')
            self.assertIsNone(args.wd_dir)
            path.write_text('{"port": "bad"}',encoding='utf-8')
            with self.assertRaises(ValueError):load_config(path)

    def test_tag_conflicts_preserve_other_attributes_and_weights(self):
        tags='black_hair, long_hair, white_dress, white_shirt, outdoors, watermark'
        selected,removed=filter_candidates(tags,'(blue hair:1.2), short hair, blue dress, indoors','watermark')
        self.assertEqual(selected,'white_shirt')
        self.assertEqual(len(removed),5)
        final,removed=merge_prompts({'positive':tags,'negative':'blue hair, blurry'},
                                    '(blue hair:1.2), short hair, blue dress, indoors','watermark')
        self.assertEqual(final['positive'],'white_shirt, (blue hair:1.2), short hair, blue dress, indoors')
        self.assertEqual(final['negative'],'blurry, watermark')

    def test_analysis_model_uses_runtime_setting_without_network_lookup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder, patch('urllib.request.urlopen') as network:
            data=create_app(Path(folder),model='another-model').test_client().get('/api/analysis-models').json
        self.assertEqual(data['models'],['another-model'])
        network.assert_not_called()




    def test_model_cli_override_is_validated_and_reported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'synthetic-settings.json';path.write_text(json.dumps({'model':'gemma3:4b'}),encoding='utf-8')
            args=parse_args(['--config',str(path),'--model','gemma3:12b'])
            self.assertEqual(args.model,'gemma3:12b');self.assertIn('model',args.config_overrides)
            path.write_text(json.dumps({'model':'bad name'}),encoding='utf-8')
            with self.assertRaises(ValueError):load_config(path)

if __name__=='__main__':unittest.main()
