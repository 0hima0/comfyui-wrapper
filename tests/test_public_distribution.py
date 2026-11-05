"""Public Git sources use portable examples and ignore private runtime data."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('service_renderer',ROOT/'tools/internal/render_service.py')
renderer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class PublicDistributionTests(unittest.TestCase):
    def test_service_uses_literal_working_directory_and_quoted_arguments(self):
        template=(ROOT/'deploy/systemd/comfyui-wrapper.service').read_text(encoding='utf-8')
        app=ROOT/'tests'/'example folder%name'
        result=renderer.render(template,app,'example_user')
        self.assertIn('User=example_user',result)
        self.assertIn('WorkingDirectory='+str(app.resolve()).replace('%','%%')+'\n',result)
        self.assertNotIn('WorkingDirectory="',result)
        self.assertIn(json.dumps(str(app.resolve()/'tools/user/webui.py').replace('%','%%'),ensure_ascii=False),result)
        self.assertNotRegex(result,r'@[A-Z_]+@')
        self.assertNotIn('ollama.service',result)

    def test_invalid_service_values_fail_before_writing(self):
        for user in ('bad user','example\nUser=root',''):
            with self.subTest(user=user),self.assertRaises(ValueError):
                renderer.render('@SERVICE_USER@',ROOT,user)
        for folder in ('invalid\nfolder','dollar$folder'):
            with self.subTest(folder=folder),self.assertRaises(ValueError):
                renderer.render('@APP_DIR@',ROOT/folder,'example_user')

    def test_public_config_example_is_machine_independent(self):
        dockerignore=(ROOT/'.dockerignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('internal-docs/**',dockerignore)
        self.assertNotIn('!docs/**',dockerignore)
        example=json.loads((ROOT/'config/config.example.json').read_text(encoding='utf-8'))
        self.assertIsNone(example['wd_dir'])
        self.assertEqual(example['host'],'127.0.0.1')
        patterns=(r'/home/[a-zA-Z0-9_-]+/',r'\b192\.168\.\d+\.\d+',r'\b[A-Z]:[\\/]')
        # Inspect only the public example, never actual configuration or Git credentials.
        text=(ROOT/'config/config.example.json').read_text(encoding='utf-8')
        for pattern in patterns:
            self.assertIsNone(re.search(pattern,text))

    @unittest.skipUnless(shutil.which('git'),'Git unavailable')
    def test_private_notes_and_local_config_are_git_ignored(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            folder=Path(folder)
            shutil.copyfile(ROOT/'.gitignore',folder/'.gitignore')
            env=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
            subprocess.run(['git','-C',str(folder),'init','--quiet'],check=True,capture_output=True,env=env)
            private=['local/ENVIRONMENT.md','config.json','internal-docs/README.md',
                     'settings.conf','.env','web-results/history.sqlite3',
                     '.venv/pyvenv.cfg','update-backups/example/restore.json','.update-lock/lock',
                     'AGENTS.md','.agents/local.md','.codex/state.json',
                     'config/production.json','config/service.yaml','deploy/config.json',
                     'deploy/config.json.backup','deploy/runtime.local.json',
                     '.aws/credentials','.ssh/id_ed25519','.azure/accessTokens.json',
                     '.config/gcloud/application_default_credentials.json',
                     '.git-credentials','.netrc','.npmrc','.pypirc',
                     'credentials.json','credentials.production.json','secrets.yaml',
                     'deploy/server.pem','deploy/server.key','deploy/client.p12',
                     'deploy/client.pfx','id_rsa','id_ed25519',
                     'settings.conf.bak','README.md~','deploy/unit.service.swp',
                     'src/fix.py.orig','src/fix.py.rej','backup.tar.gz',
                     'history.log.1','models/example.safetensors','tmp-check/report.json']
            public=['docs/USER_GUIDE.md','tests/test_git_update.py','scripts/user/update.sh',
                    'config/config.example.json','docs/images/first-generation-input.png',
                    '.env.example','.github/workflows/tests.yml',
                    'deploy/systemd/comfyui-wrapper.service','workflows/anima_template.json',
                    'tests/fixtures/routes.json','web/static/webui.js','requirements.txt']
            paths=private+public
            result=subprocess.run(['git','-C',str(folder),'check-ignore','--stdin'],input=('\n'.join(paths)+'\n').encode(),capture_output=True,env=env,check=True)
            self.assertEqual(result.stdout.decode().splitlines(),private)
