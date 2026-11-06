"""ComfyUI checkpoint discovery and model family classification."""
import json
import urllib.request
from comfyui_wrapper.models import model_families
from comfyui_wrapper.app_metadata import BASE
from comfyui_wrapper.workflows import builders
class ModelCatalog:
    def __init__(self, runtime):
        self.runtime = runtime

    def default_checkpoint(self, target):
        if target == 'anima':
            try:
                template = builders.load_anima_template(BASE / 'workflows' / 'anima_template.json')
                return next(n['widgets_values'][0] for n in template['nodes'] if n['id'] == 44 and n['type'] == 'UNETLoader')
            except (ValueError, KeyError, TypeError, IndexError, StopIteration):
                return ''
        return 'AnimagineXL_v31.safetensors'

    def checkpoints(self, target):
        kind, field = ('UNETLoader', 'unet_name') if target == 'anima' else ('CheckpointLoaderSimple', 'ckpt_name')
        default = self.default_checkpoint(target)
        try:
            with urllib.request.urlopen(self.runtime.comfy_url.rstrip('/') + '/object_info/' + kind, timeout=5) as response:
                info = json.load(response)
            names = info[kind]['input']['required'][field][0]
            if not isinstance(names, list) or not all((isinstance(n, str) and n for n in names)):
                raise ValueError('Invalid model list')
            names = sorted(set(names), key=str.casefold)
            warning = '' if names else 'ComfyUIに対応するモデルがありません。'
            if target == 'anima' and not default:
                warning += 'Animaワークフローを workflows/anima_template.json に配置してください。workflows/README.md を参照してください。'
            return dict(names=names, default=default if default in names else names[0] if names else '', source='comfyui', warning=warning)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return dict(names=[default] if default else [], default=default, source='fallback', warning='ComfyUIの起動・接続先を確認してください。Animaを使う場合は workflows/anima_template.json の配置も確認してください。')

    def classify(self, target, name):
        family, source = model_families.checkpoint_family(target, name, self.runtime.checkpoint_families)
        return dict(family=family, family_label=model_families.LABELS[family], family_source=source,
                    lora_folders=model_families.checkpoint_lora_paths(name,getattr(self.runtime,'checkpoint_lora_folders',{})))
