import unittest
from comfyui_wrapper.workflows.sdxl_options import generation_settings


class GenerationSettingsTests(unittest.TestCase):
    def test_explicit_controls_override_restored_values_and_profile_defaults(self):
        settings=generation_settings('animagine4',{'steps':'40','cfg':'6.5'},
            {'steps':35,'sampler_name':'custom_sampler','denoise':.75})
        self.assertEqual(settings['steps'],40)
        self.assertEqual(settings['cfg'],6.5)
        self.assertEqual(settings['sampler_name'],'custom_sampler')
        self.assertEqual(settings['denoise'],.75)
        self.assertEqual(generation_settings('animagine4',{})['denoise'],1)

    def test_invalid_restored_values_and_nonfinite_overrides_are_rejected(self):
        for restored in (None,[],{'unknown':1},{'steps':True},{'cfg':False},{'steps':0},{'denoise':1.1}):
            with self.subTest(restored=restored),self.assertRaises(ValueError):
                generation_settings('animagine4',{},restored)
        for overrides in ({'cfg':'nan'},{'cfg':'inf'},{'steps':'1.5'},{'scheduler':''},{'denoise':'-1'}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                generation_settings('animagine4',overrides)
