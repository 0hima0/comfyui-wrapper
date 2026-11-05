import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import urllib.error
from comfyui_wrapper.system import check_installation


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.temp.name).resolve()
        (self.root/'.git').mkdir()
        (self.root/'VERSION').write_text('test-release\n',encoding='utf-8')
        self.dirty=False
        self.git_patch=patch.object(check_installation.subprocess,'run',side_effect=self.git)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def git(self,command,**kwargs):
        from subprocess import CompletedProcess
        args=command[3:]
        values={('rev-parse','--show-toplevel'):str(self.root),
                ('rev-parse','HEAD'):'a'*40,
                ('status','--porcelain','--untracked-files=no'):' M requirements.txt' if self.dirty else '',
                ('ls-files','-v'):'H VERSION\nH requirements.txt'}
        return CompletedProcess(command,0,values[tuple(args)].encode('utf-8'),b'')

    def tearDown(self):self.temp.cleanup()

    def verify(self,response):
        with patch('urllib.request.urlopen',side_effect=response),redirect_stdout(io.StringIO()) as output:
            result=check_installation.main(['--directory',str(self.root),'--url','http://127.0.0.1:7860'])
        return result,output.getvalue()

    def server_responses(self):
        return [io.BytesIO(json.dumps(dict(release='test-release',app_directory=str(self.root),pid=123,lora_samples_api=True,lora_samples_form=True)).encode()),io.BytesIO(b'{"names":[]}')]

    def test_matching_installation(self):self.assertEqual(self.verify(self.server_responses())[0],0)

    def test_partial_update(self):
        self.dirty=True
        result,output=self.verify(self.server_responses());self.assertEqual(result,1);self.assertIn('ローカル変更',output)

    def test_non_git_installation_reports_migration_without_contacting_server(self):
        (self.root/'.git').rmdir()
        with patch('urllib.request.urlopen') as request,redirect_stdout(io.StringIO()):
            self.assertEqual(check_installation.main(['--directory',str(self.root)]),1)
            request.assert_not_called()

    def test_older_server_without_api(self):
        result,output=self.verify([urllib.error.HTTPError('url',404,'missing',{},None)])
        self.assertEqual(result,1);self.assertIn('404',output)


if __name__=='__main__':unittest.main()
