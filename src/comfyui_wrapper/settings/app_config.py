import json
import re
from urllib.parse import urlsplit
from pathlib import Path
from comfyui_wrapper.app_metadata import ANALYSIS_MODEL
from comfyui_wrapper.models.model_families import validate_checkpoint_lora_folders

DEFAULTS = dict(host='127.0.0.1',port=7860,ollama_url='http://127.0.0.1:11434',
                comfy_url='http://127.0.0.1:8188',ollama_urls=[],ollama_keep_alive=0,model=ANALYSIS_MODEL,
                wd_dir=None,output_dir='web-results',checkpoint_families={},lora_folders={},checkpoint_lora_folders={},gallery_retention_days=10)


def validate_gallery_retention_days(value):
    if type(value) is not int or not 0 <= value <= 36500:
        raise ValueError('gallery_retention_daysは0〜36500の整数です（0は自動削除しない）。')
    return value


def validate_analysis_model(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,299}',value.strip()):
        raise ValueError('解析モデルはOllamaのモデル名を300文字以内で指定してください（例：gemma3:4b）。')
    return value.strip()


def validate_ollama_urls(value):
    if not isinstance(value,list) or len(value)>4:
        raise ValueError('ollama_urlsは最大4件のURLの配列で指定してください')
    urls=[]
    for item in value:
        if not isinstance(item,str):raise ValueError('ollama_urlsのURLが不正です')
        url=item.strip().rstrip('/')
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError('ollama_urlsはhttpまたはhttpsの接続先を指定してください')
        if url in urls:raise ValueError('ollama_urlsに同じ接続先が重複しています')
        urls.append(url)
    return urls


def validate_keep_alive(value):
    if (type(value) is int and value>=-1) or (isinstance(value,str) and re.fullmatch(r'(?:-1|0|[1-9][0-9]*[smh])',value)):
        return value
    raise ValueError('ollama_keep_aliveは秒数の整数、-1、0、または10mなどの期間で指定してください')


def load_config(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if not isinstance(data,dict) or set(data)-set(DEFAULTS):
        raise ValueError('設定ファイルの項目が不正です')
    result = {**DEFAULTS,**data}
    result['checkpoint_lora_folders']=validate_checkpoint_lora_folders(result['checkpoint_lora_folders'])
    result['model']=validate_analysis_model(result['model'])
    result['ollama_urls']=validate_ollama_urls(result['ollama_urls'])
    result['ollama_keep_alive']=validate_keep_alive(result['ollama_keep_alive'])
    result['gallery_retention_days']=validate_gallery_retention_days(result['gallery_retention_days'])
    for key in ('checkpoint_families','lora_folders'):
        mapping=result[key]
        if not isinstance(mapping,dict) or any(not isinstance(name,str) or not name.strip('/\\')
                or family not in ('sd15','sdxl','illustrious') for name,family in mapping.items()):
            raise ValueError(key+'は名前とsd15／sdxl／illustriousの対応表を指定してください')
    if type(result['port']) is not int or not 1 <= result['port'] <= 65535:
        raise ValueError('portは1〜65535の整数です')
    for name in ('host','model','ollama_url','comfy_url','output_dir'):
        if not isinstance(result[name],str) or not result[name].strip():
            raise ValueError('設定値が不正です: '+name)
    for name in ('wd_dir','output_dir'):
        if result[name] is not None:
            p=Path(result[name]).expanduser()
            result[name]=p if p.is_absolute() else path.parent/p
    return result
