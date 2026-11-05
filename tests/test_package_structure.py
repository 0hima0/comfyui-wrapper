"""Package imports must survive module relocation."""
import importlib
import pkgutil
import unittest
import comfyui_wrapper

class PackageStructureTests(unittest.TestCase):
    def test_all_application_modules_import_without_starting_services(self):
        for module in pkgutil.walk_packages(comfyui_wrapper.__path__, (comfyui_wrapper.__name__ + '.')):
            with self.subTest(module=module.name):
                importlib.import_module(module.name)

