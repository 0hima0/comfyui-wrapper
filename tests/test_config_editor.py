"""Config editor regression cases operate exclusively on synthetic temporary files."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from comfyui_wrapper.settings.app_config import DEFAULTS
from comfyui_wrapper.settings.config_editor import ConfigEditor, ConfigConflict
from comfyui_wrapper.webui import create_app


class ConfigEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'example-settings.json'
        self.initial=copy.deepcopy(DEFAULTS)
        self.path.write_text(json.dumps(self.initial),encoding='utf-8')
        self.editor=ConfigEditor(self.path)

    def candidate(self):
        current=self.editor.read()
        data=copy.deepcopy(current['settings']);data['port']=7871
        return current,data

    def test_review_does_not_write_and_save_backs_up_exact_original(self):
        original=self.path.read_bytes()
        current,data=self.candidate()
        reviewed=self.editor.review(data,current['revision'])
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual([row['key'] for row in reviewed['changes']],['port'])
        result=self.editor.save(data,current['revision'],reviewed['confirmation'])
        self.assertTrue(result['restart_required'])
        self.assertEqual((self.root/result['backup']).read_bytes(),original)
        self.assertEqual(json.loads(self.path.read_text())['port'],7871)

    def test_analysis_model_edit_preserves_value_and_requires_restart(self):
        current=self.editor.read();data=copy.deepcopy(current['settings']);data['model']='gemma3:4b'
        reviewed=self.editor.review(data,current['revision'])
        self.assertEqual([row['key'] for row in reviewed['changes']],['model'])
        self.editor.save(data,current['revision'],reviewed['confirmation'])
        self.assertEqual(self.editor.read()['settings']['model'],'gemma3:4b')
        self.assertEqual(create_app(self.root/'old').extensions['app_services'].runtime.analysis_model,'qwen3-vl:8b-instruct')
        self.assertEqual(create_app(self.root/'new',model='gemma3:4b').extensions['app_services'].runtime.analysis_model,'gemma3:4b')
        current=self.editor.read()
        for invalid in ['',None,False,'a b','bad\nname','x'*301]:
            bad=copy.deepcopy(current['settings']);bad['model']=invalid
            with self.subTest(value=invalid),self.assertRaises(ValueError):self.editor.review(bad,current['revision'])
        self.assertEqual(self.editor.read()['settings']['model'],'gemma3:4b')

    def test_external_change_requires_reloading_and_does_not_overwrite(self):
        current,data=self.candidate();reviewed=self.editor.review(data,current['revision'])
        self.path.write_text(json.dumps(dict(self.initial,port=7872)),encoding='utf-8')
        with self.assertRaises(ConfigConflict):
            self.editor.save(data,current['revision'],reviewed['confirmation'])
        self.assertEqual(json.loads(self.path.read_text())['port'],7872)

    def test_changed_candidate_requires_new_confirmation(self):
        current,data=self.candidate();reviewed=self.editor.review(data,current['revision'])
        data['port']=7873
        with self.assertRaises(ConfigConflict):
            self.editor.save(data,current['revision'],reviewed['confirmation'])
        self.assertEqual(json.loads(self.path.read_text()),self.initial)

    def test_invalid_settings_never_replace_file(self):
        current,data=self.candidate()
        for key,value in [('port',0),('comfy_url','file:///not-a-service'),('wd_dir',str(self.root/'missing-wd')),('checkpoint_families',{'example':'invalid'})]:
            candidate=copy.deepcopy(data);candidate[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.editor.review(candidate,current['revision'])
        self.assertEqual(json.loads(self.path.read_text()),self.initial)

    def test_retention_edit_validates_and_requires_restart(self):
        current=self.editor.read();data=copy.deepcopy(current['settings'])
        for invalid in (-1,36501,True,1.5,'30',None):
            data['gallery_retention_days']=invalid
            with self.subTest(value=invalid),self.assertRaises(ValueError):
                self.editor.review(data,current['revision'])
        data['gallery_retention_days']=0
        reviewed=self.editor.review(data,current['revision'])
        result=self.editor.save(data,current['revision'],reviewed['confirmation'])
        self.assertTrue(result['restart_required'])
        self.assertEqual(self.editor.read()['settings']['gallery_retention_days'],0)
        # Older files missing the key still round-trip with the default policy.
        del self.initial['gallery_retention_days']
        self.path.write_text(json.dumps(self.initial),encoding='utf-8')
        current=self.editor.read();data=copy.deepcopy(current['settings']);data['port']=7872
        self.assertEqual(data['gallery_retention_days'],10)
        reviewed=self.editor.review(data,current['revision'])
        self.editor.save(data,current['revision'],reviewed['confirmation'])
        self.assertEqual(self.editor.read()['settings']['gallery_retention_days'],10)

    def test_replace_failure_keeps_original_and_removes_temporary_file(self):
        current,data=self.candidate();reviewed=self.editor.review(data,current['revision'])
        with patch('comfyui_wrapper.settings.config_editor.Path.replace',side_effect=PermissionError('blocked')):
            with self.assertRaises(PermissionError):
                self.editor.save(data,current['revision'],reviewed['confirmation'])
        self.assertEqual(json.loads(self.path.read_text()),self.initial)
        self.assertFalse(list(self.root.glob('*.tmp-*')))
        self.assertEqual(len(list(self.root.glob('*.backup-*'))),1)

    def test_ui_guards_busy_job_and_does_not_apply_saved_values(self):
        app=create_app(self.root/'output');app.extensions['config_editor']=self.editor
        client=app.test_client();headers={'X-Requested-With':'LLMPC'}
        self.assertEqual(client.get('/api/app-settings').status_code,403)
        self.assertEqual(client.get('/api/app-settings',headers=headers).status_code,200)
        current,data=self.candidate()
        preview=client.post('/api/app-settings',json=dict(settings=data,revision=current['revision']),headers=headers)
        self.assertEqual(preview.status_code,200)
        body=dict(settings=data,revision=current['revision'],confirmation=preview.json['confirmation'])
        services=app.extensions['app_services'];services.runner.busy.acquire()
        try:self.assertEqual(client.put('/api/app-settings',json=body,headers=headers).status_code,409)
        finally:services.runner.busy.release()
        self.assertEqual(client.put('/api/app-settings',json=body,headers=headers).status_code,200)
        self.assertEqual(services.runtime.comfy_url,DEFAULTS['comfy_url'])
        self.assertFalse(services.runner.busy.locked())

    def test_connection_check_does_not_save_settings(self):
        app=create_app(self.root/'output');app.extensions['config_editor']=self.editor
        _,data=self.candidate()
        with patch('comfyui_wrapper.routes.app_settings.comfy_client.api',side_effect=[{'system':{}},{'models':[]}]):
            result=app.test_client().post('/api/app-settings',json=dict(action='connection',settings=data),headers={'X-Requested-With':'LLMPC'})
        self.assertEqual(result.status_code,200)
        self.assertTrue(all(row['ok'] for row in result.json['results']))
        self.assertEqual(json.loads(self.path.read_text()),self.initial)
