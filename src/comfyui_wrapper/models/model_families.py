"""Conservative family matching based on declared folders and known names."""
import re

LABELS = {'sd15': 'SD1.5', 'sdxl': 'SDXL', 'illustrious': 'Illustrious (SDXL)',
          'anima': 'Anima', 'unknown': '未判定'}


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def parts(name):
    return name.replace('\\', '/').split('/')


def folder_family(name, mapping=None):
    folders = parts(name)[:-1]
    path = '/'.join(folders).casefold()
    matches = [(len(key), family) for key, family in (mapping or {}).items()
               if path == key.replace('\\', '/').strip('/').casefold()
               or path.startswith(key.replace('\\', '/').strip('/').casefold() + '/')]
    if matches:
        return max(matches)[1]
    for folder in reversed(folders):
        token = normalized(folder)
        if token in ('illustrious', 'illustriousxl', 'wai', 'wai17', 'waiv17'):
            return 'illustrious'
        if token in ('sd15', 'sd1', 'stablediffusion15', 'stablediffusion1'):
            return 'sd15'
        if token in ('sdxl', 'stablediffusionxl', 'animagine', 'animaginexl'):
            return 'sdxl'
    return 'unknown'


def checkpoint_family(target, name, overrides=None):
    if target == 'anima':
        return 'anima', 'loader'
    key = '/'.join(parts(name))
    for candidate, family in (overrides or {}).items():
        if '/'.join(parts(candidate)).casefold() == key.casefold():
            return family, 'config'
    # Specific derivative names take priority over broad SDXL parent folders.
    stem = normalized(parts(name)[-1])
    if 'illustrious' in stem or re.match(r'wai.*v1[0-9]', stem):
        return 'illustrious', 'filename'
    folder = folder_family(name)
    if folder != 'unknown':
        return folder, 'folder'
    if 'animagine' in stem or 'sdxl' in stem:
        return 'sdxl', 'filename'
    if 'sd15' in stem or 'stablediffusionv15' in stem or stem.startswith('v15pruned'):
        return 'sd15', 'filename'
    return 'unknown', 'unknown'


def compatible(checkpoint_kind, lora_name, folders=None):
    return checkpoint_kind in ('sd15', 'sdxl', 'illustrious') and folder_family(lora_name, folders) == checkpoint_kind


def validate_checkpoint_lora_folders(value):
    if not isinstance(value,dict) or len(value)>1000:raise ValueError('モデルとLoRAフォルダーの対応は1000モデル以内で指定してください。')
    result={};seen=set()
    def relative(text,root=False):
        if not isinstance(text,str) or not text.strip() or len(text)>1000 or any(ord(c)<32 for c in text):raise ValueError('モデル名・フォルダー名が不正です。')
        text=text.strip().replace('\\','/').rstrip('/')
        if root and text=='.':return text
        if any(part in ('','.','..') or ':' in part for part in text.split('/')):raise ValueError('ComfyUI内の相対パスを指定してください。')
        return text
    for name,folders in value.items():
        name=relative(name)
        if name.casefold() in seen:raise ValueError('生成モデルの対応が重複しています。')
        seen.add(name.casefold())
        if not isinstance(folders,list) or len(folders)>100:raise ValueError('LoRAフォルダーはモデルごとに100件以内の配列で指定してください。')
        result[name]=list(dict.fromkeys(relative(folder,True) for folder in folders))
    return result


def checkpoint_lora_paths(name,mapping=None):
    key='/'.join(parts(name)).casefold()
    for model,folders in (mapping or {}).items():
        if '/'.join(parts(model)).casefold()==key:return list(folders)
    return None


def in_lora_folders(name,folders):
    parent='/'.join(parts(name)[:-1]).casefold()
    return any((not parent if folder=='.' else parent==folder.casefold() or parent.startswith(folder.casefold()+'/')) for folder in folders)


def allowed_lora(target,checkpoint,family,name,legacy=None,mapping=None):
    if target=='anima':return False
    folders=checkpoint_lora_paths(checkpoint,mapping)
    return in_lora_folders(name,folders) if folders is not None else compatible(family,name,legacy)
