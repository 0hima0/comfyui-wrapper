"""ComfyUI checkpoint discovery and model family classification."""
import json
import urllib.request
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.models import model_families
from comfyui_wrapper.app_metadata import BASE
class ModelCatalog:
    def __init__(self, runtime):
        self.runtime = runtime

    def default_checkpoint(self, target):
        if target == 'anima':
            template = generate.read_json(BASE / 'workflows' / 'anima_template.json')
            return next((n['widgets_values'][0] for n in template['nodes'] if n['id'] == 44))
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
            return dict(names=names, default=default if default in names else names[0] if names else '', source='comfyui', warning='' if names else 'ComfyUIに対応するモデルがありません。')
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return dict(names=[default], default=default, source='fallback', warning='ComfyUIに接続できないため既定のモデルのみ表示しています。起動と接続先を確認して一覧を更新してください。')

    def classify(self, target, name):
        family, source = model_families.checkpoint_family(target, name, self.runtime.checkpoint_families)
        return dict(family=family, family_label=model_families.LABELS[family], family_source=source,
                    lora_folders=model_families.checkpoint_lora_paths(name,getattr(self.runtime,'checkpoint_lora_folders',{})))
