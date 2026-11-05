"""Local server controls used by the Git updater."""
import importlib.util
import unittest
from unittest.mock import patch, Mock
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('update_app',ROOT/'tools/internal/update_app.py')
updater=importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpdateControlTests(unittest.TestCase):
    def test_local_control_urls_only(self):
        self.assertEqual(updater.local_url('http://127.0.0.1:7860/'),'http://127.0.0.1:7860')
        for url in ('http://example.com','http://user:pass@localhost','http://localhost/path'):
            with self.assertRaises(ValueError):updater.local_url(url)


class ServiceMigrationTests(unittest.TestCase):
    def test_detects_legacy_service(self):
        with patch.object(updater.os, 'name', 'posix'), patch.object(updater.shutil, 'which', return_value='/bin/systemctl'), patch.object(updater.subprocess, 'run', side_effect=[Mock(returncode=3), Mock(returncode=0)]):
            self.assertEqual(updater.service_active(), 'llmpc-image-webui.service')

    def test_rejects_two_active_services(self):
        with patch.object(updater.os, 'name', 'posix'), patch.object(updater.shutil, 'which', return_value='/bin/systemctl'), patch.object(updater.subprocess, 'run', return_value=Mock(returncode=0)):
            with self.assertRaises(RuntimeError):
                updater.service_active()
