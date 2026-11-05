"""Version bumps and all runtime metadata share the same version source."""
from pathlib import Path
import unittest
from comfyui_wrapper.app_metadata import RELEASE
from comfyui_wrapper.versioning import parse_version, bump_version


class VersioningTests(unittest.TestCase):
    def test_increment_resets_lower_components(self):
        self.assertEqual(bump_version('1.2.3','patch'),'1.2.4')
        self.assertEqual(bump_version('1.2.3','minor'),'1.3.0')
        self.assertEqual(bump_version('1.2.3','major'),'2.0.0')

    def test_invalid_versions(self):
        for value in ('1.2','01.2.3','v1.2.3','1.2.3-dev',None):
            with self.subTest(value=value),self.assertRaises(ValueError):parse_version(value)

    def test_runtime_matches_version_file(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(RELEASE,(root/'VERSION').read_text(encoding='utf-8').strip())