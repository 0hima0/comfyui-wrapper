"""Offline Git updates using disposable repositories and synthetic saved data."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch

from tests.test_update_app import updater
from comfyui_wrapper.system import check_installation

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('git'), 'Git unavailable')
class GitUpdateTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
            'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        (ROOT/'tmp-test-runtime').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp-test-runtime')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base/'source'
        self.root = self.base/'installed'
        self.remote.mkdir()
        self.git(self.remote, 'init', '-b', 'main')
        files = {
            'VERSION': 'test-v1\n', 'requirements.txt': '# synthetic\n',
            'tools/user/webui.py': '# synthetic\n',
            'src/comfyui_wrapper/webui.py': '# synthetic\n',
            'scripts/user/start-webui.sh': '# synthetic\n',
            'scripts/user/update.sh': '# synthetic\n',
            'tools/internal/update_app.py': '# synthetic\n',
            'obsolete.txt': 'old',
            '.gitignore': 'config.json\nweb-results/\nupdate-backups/\n.update-lock/\nlocal/\n',
        }
        for name, content in files.items():
            self.write(self.remote, name, content)
        self.commit()
        self.git(self.base, 'clone', str(self.remote), str(self.root))
        self.old = self.git(self.root, 'rev-parse', 'HEAD')
        self.config = self.root/'config.json'
        self.output = self.root/'web-results'
        self.write(self.root, 'config.json', json.dumps({'output_dir': 'web-results', 'port': 7860}))
        self.write(self.root, 'web-results/synthetic.txt', 'preserve me')
        self.write(self.remote, 'VERSION', 'test-v2\n')
        self.write(self.remote, 'docs/images/example.png', 'synthetic, not a real image')
        (self.remote/'obsolete.txt').unlink()
        self.commit()
        self.target = self.git(self.remote, 'rev-parse', 'HEAD')

    def git(self, root, *args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True)
        return result.stdout.decode('utf-8').strip()

    def write(self, root, name, value):
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def commit(self):
        self.git(self.remote, 'add', '-A')
        self.git(self.remote, 'commit', '-m', 'Synthetic change')

    def plan(self):
        plan = updater.GitUpdate(self.root)
        plan.prepare(self.config, self.output)
        return plan

    def test_fast_forward_adds_deletes_and_preserves_ignored_data(self):
        plan = self.plan()
        plan.install()
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.target)
        self.assertTrue((self.root/'docs/images/example.png').is_file())
        self.assertFalse((self.root/'obsolete.txt').exists())
        self.assertEqual((self.output/'synthetic.txt').read_text(), 'preserve me')
        self.assertTrue(self.config.is_file())
        plan.rollback()
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.old)
        self.assertTrue((self.root/'obsolete.txt').exists())
        self.assertFalse((self.root/'docs/images/example.png').exists())

    def test_local_changes_are_not_overwritten(self):
        self.write(self.root, 'VERSION', 'local edit')
        with self.assertRaisesRegex(ValueError, 'local changes'):
            self.plan()
        self.assertEqual((self.root/'VERSION').read_text(), 'local edit')

    def test_divergent_commit_is_not_reset(self):
        self.write(self.root, 'local-commit.txt', 'keep')
        self.git(self.root, 'add', 'local-commit.txt')
        self.git(self.root, 'commit', '-m', 'Local work')
        with self.assertRaisesRegex(ValueError, 'diverged'):
            self.plan()
        self.assertTrue((self.root/'local-commit.txt').is_file())

    def test_untracked_collision_is_preserved(self):
        self.write(self.root, 'docs/images/example.png', 'local')
        with self.assertRaisesRegex(ValueError, 'overwrite a local'):
            self.plan()
        self.assertEqual((self.root/'docs/images/example.png').read_text(), 'local')

    def test_ignored_collision_is_preserved(self):
        self.write(self.root, '.git/info/exclude', 'docs/images/\n')
        self.test_untracked_collision_is_preserved()

    def test_private_target_is_rejected(self):
        self.write(self.remote, 'settings.conf', 'synthetic only')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'private or runtime'):
            self.plan()

    def test_target_cannot_remove_the_update_entry_point(self):
        (self.remote/'scripts/user/update.sh').unlink()
        self.commit()
        with self.assertRaisesRegex(ValueError, 'Required application files'):
            self.plan()

    def test_custom_output_overlap_is_rejected(self):
        self.output = self.root/'docs'
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.plan()

    def test_detached_head_is_rejected(self):
        self.git(self.root, 'checkout', '--detach')
        with self.assertRaises(RuntimeError):
            self.plan()

    def test_skip_worktree_is_rejected(self):
        self.git(self.root, 'update-index', '--skip-worktree', 'VERSION')
        with self.assertRaisesRegex(ValueError, 'Sparse checkout'):
            self.plan()

    def test_git_symlink_entry_is_rejected_without_creating_a_link(self):
        blob = self.git(self.remote, 'rev-parse', 'HEAD:VERSION')
        self.git(self.remote, 'update-index', '--add', '--cacheinfo', '120000,' + blob + ',linked-file')
        self.git(self.remote, 'commit', '-m', 'Synthetic symlink entry')
        with self.assertRaisesRegex(ValueError, 'symlinks or submodules'):
            self.plan()

    def test_zip_argument_is_rejected_before_configuration_read(self):
        with patch.object(updater, 'ROOT', self.root), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                updater.main(['nonexistent.zip'])
            self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.root/'.update-lock').exists())

    def test_non_git_installation_is_rejected_before_configuration_read(self):
        archive_install = self.base/'old-zip-install'
        archive_install.mkdir()
        with patch.object(updater, 'ROOT', archive_install):
            with self.assertRaisesRegex(ValueError, 'requires a Git clone'):
                updater.main([])

    def test_help_has_no_side_effect_on_application(self):
        with patch.object(updater, 'ROOT', self.root), redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as error:
                updater.main(['--help'])
            self.assertEqual(error.exception.code, 0)
        self.assertNotIn('archive', output.getvalue())
        self.assertFalse((self.root/'.update-lock').exists())
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.old)

    def test_fetch_failure_does_not_change_checkout(self):
        self.git(self.root, 'remote', 'set-url', 'origin', str(self.base/'missing-source'))
        with self.assertRaisesRegex(RuntimeError, 'Git fetch failed'):
            self.plan()
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.old)

    def test_new_edits_after_prepare_are_not_discarded(self):
        plan = self.plan()
        self.write(self.root, 'VERSION', 'local after prepare')
        with self.assertRaises(ValueError):
            plan.install()
        plan.rollback()
        self.assertEqual((self.root/'VERSION').read_text(), 'local after prepare')

    def run_update(self, startup_failure=False):
        real_run = subprocess.run
        def run(command, **kwargs):
            if len(command) > 2 and command[1:3] == ['-m', 'pip']:
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)
        def ready(*args):
            if startup_failure:
                self.write(self.root, 'web-results/synthetic.txt', 'changed by new app')
                raise RuntimeError('Synthetic startup failure')
        with ExitStack() as stack:
            stack.enter_context(patch.object(updater, 'ROOT', self.root))
            stack.enter_context(patch.object(updater.subprocess, 'run', side_effect=run))
            stack.enter_context(patch.object(updater, 'server_info', return_value={'release': 'test-v1'}))
            stack.enter_context(patch.object(updater, 'service_active', return_value=None))
            stack.enter_context(patch.object(updater, 'stop_server'))
            stack.enter_context(patch.object(updater, 'start_server', return_value=None))
            stack.enter_context(patch.object(updater, 'wait_ready', side_effect=ready))
            stack.enter_context(redirect_stdout(io.StringIO()))
            return updater.main(['--config', str(self.config)])

    def test_transaction_records_commits_and_backs_up_data(self):
        self.assertEqual(self.run_update(), 0)
        restores = list((self.root/'update-backups').glob('*/restore.json'))
        self.assertEqual(len(restores), 1)
        saved = json.loads(restores[0].read_text())
        self.assertEqual(saved['git_before'], self.old)
        self.assertEqual(saved['git_after'], self.target)
        self.assertEqual((restores[0].parent/'data/synthetic.txt').read_text(), 'preserve me')

    def test_startup_failure_restores_git_and_data(self):
        with self.assertRaisesRegex(RuntimeError, 'Synthetic startup'):
            self.run_update(startup_failure=True)
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.old)
        self.assertEqual((self.output/'synthetic.txt').read_text(), 'preserve me')
        self.assertFalse((self.root/'.update-lock').exists())

    def test_no_update_does_not_stop_server(self):
        self.plan().install()
        with patch.object(updater, 'ROOT', self.root), patch.object(updater, 'stop_server') as stop:
            self.assertEqual(updater.main(['--config', str(self.config)]), 0)
            stop.assert_not_called()

    def test_git_installation_diagnostic_without_manifest(self):
        responses = [io.BytesIO(json.dumps(dict(release='test-v1', app_directory=str(self.root),
            pid=123, lora_samples_api=True, lora_samples_form=True)).encode()), io.BytesIO(b'{"names":[]}')]
        with patch('urllib.request.urlopen', side_effect=responses), redirect_stdout(io.StringIO()):
            self.assertEqual(check_installation.main(['--directory', str(self.root)]), 0)

    def test_git_installation_diagnostic_detects_local_changes(self):
        self.write(self.root, 'requirements.txt', '# local edit')
        responses = [io.BytesIO(json.dumps(dict(release='test-v1', app_directory=str(self.root),
            pid=123, lora_samples_api=True, lora_samples_form=True)).encode()), io.BytesIO(b'{"names":[]}')]
        with patch('urllib.request.urlopen', side_effect=responses), redirect_stdout(io.StringIO()):
            self.assertEqual(check_installation.main(['--directory', str(self.root)]), 1)
