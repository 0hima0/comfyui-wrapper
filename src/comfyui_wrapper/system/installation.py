"""Read installed assets and compare stable ComfyUI releases without modifying servers."""
import json
import re
import urllib.request
from datetime import datetime, timezone
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.models import model_families

RELEASES = 'https://github.com/Comfy-Org/ComfyUI/releases'
LATEST_API = 'https://api.github.com/repos/Comfy-Org/ComfyUI/releases/latest'


def inventory(services):
    rows, warnings = [], []
    for target in ('anima', 'animagine'):
        choices = services.catalog.checkpoints(target)
        if choices['source'] != 'comfyui':
            warnings.append(choices.get('warning') or 'モデル一覧を取得できません。')
            continue
        for name in choices['names']:
            rows.append(dict(kind='生成モデル', name=name, **services.catalog.classify(target, name)))
    try:
        info = comfy_client.api(services.runtime.comfy_url, '/object_info/LoraLoader', timeout=5)
        names = info['LoraLoader']['input']['required']['lora_name'][0]
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ValueError('Invalid LoRA list')
        for name in sorted(set(names)):
            family = model_families.folder_family(name, services.runtime.lora_folders)
            rows.append(dict(kind='LoRA', name=name, family=family, family_label=model_families.LABELS[family]))
    except (comfy_client.ComfyError, KeyError, TypeError, IndexError, ValueError):
        warnings.append('ComfyUIのLoRA一覧を取得できません。接続とLoraLoaderを確認してください。')
    unique = {(row['kind'], row['name']): row for row in rows}
    return dict(items=sorted(unique.values(), key=lambda row:(row['kind'], row['name'].casefold())), warnings=list(dict.fromkeys(warnings)))


def stable_version(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value.strip())
    return tuple(map(int, match.groups())) if match else None


def check_update(comfy_url):
    result = dict(state='unknown', current=None, latest=None, release_url=RELEASES,
                  checked_at=datetime.now(timezone.utc).isoformat(), warnings=[])
    try:
        stats = comfy_client.api(comfy_url, '/system_stats', timeout=5)
        current = stats.get('system', {}).get('comfyui_version')
        if isinstance(current, str):
            result['current'] = current[:100]
        else:
            result['warnings'].append('稼働中のComfyUIからバージョンを取得できません。')
    except (comfy_client.ComfyError, AttributeError, TypeError):
        result['warnings'].append('ComfyUIに接続できないため、稼働バージョンは不明です。')
    try:
        request = urllib.request.Request(LATEST_API, headers={'Accept':'application/vnd.github+json', 'User-Agent':'ComfyUI-Wrapper'})
        with urllib.request.urlopen(request, timeout=10) as response:
            release = json.load(response)
        tag = release.get('tag_name')
        if stable_version(tag) is None or release.get('draft') or release.get('prerelease'):
            raise ValueError('Invalid stable release')
        result['latest'] = tag
    except (OSError, ValueError, AttributeError, TypeError):
        result['warnings'].append('公式の最新リリースを取得できません。インターネット接続またはGitHubの利用制限を確認してください。')
    current, latest = stable_version(result['current']), stable_version(result['latest'])
    if current is not None and latest is not None:
        result['state'] = 'update_available' if current < latest else 'up_to_date' if current == latest else 'ahead'
    elif result['current'] and current is None:
        result['warnings'].append('開発版などのバージョン表記のため、自動比較できません。')
    return result