"""Review and atomically save application settings; never apply them to running jobs."""
import copy
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from comfyui_wrapper.settings.app_config import DEFAULTS, validate_ollama_urls, validate_keep_alive, validate_analysis_model, validate_gallery_retention_days


from comfyui_wrapper.models.model_families import validate_checkpoint_lora_folders


class ConfigConflict(ValueError):
    pass


def validate(data, path):
    if not isinstance(data, dict) or set(data) != set(DEFAULTS):
        raise ValueError('設定項目が不足しているか、未対応の項目があります。')
    data = copy.deepcopy(data)
    data['checkpoint_lora_folders']=validate_checkpoint_lora_folders(data['checkpoint_lora_folders'])
    data['model']=validate_analysis_model(data['model'])
    data['gallery_retention_days']=validate_gallery_retention_days(data['gallery_retention_days'])
    if not isinstance(data['host'],str) or not re.fullmatch(r'[a-zA-Z0-9_.:\-]+',data['host']):
        raise ValueError('待受アドレスを確認してください。')
    if type(data['port']) is not int or not 1 <= data['port'] <= 65535:
        raise ValueError('ポートは1〜65535の整数です。')
    data['ollama_urls'] = validate_ollama_urls(data['ollama_urls'])
    data['ollama_keep_alive'] = validate_keep_alive(data['ollama_keep_alive'])
    for url in [data['ollama_url'],data['comfy_url'],*data['ollama_urls']]:
        if not isinstance(url,str) or len(url)>2000:
            raise ValueError('接続先URLを確認してください。')
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('接続先は認証情報やクエリを含まないhttp/https URLで指定してください。')
        try:
            parsed.port
        except ValueError:
            raise ValueError('接続先のポートを確認してください。')
    for key in ('checkpoint_families','lora_folders'):
        mapping=data[key]
        if not isinstance(mapping,dict) or len(mapping)>1000 or any(not isinstance(name,str) or not name.strip('/\\') or len(name)>1000 or family not in ('sd15','sdxl','illustrious') for name,family in mapping.items()):
            raise ValueError(key+'の名前とモデル系列を確認してください。')
    for key in ('wd_dir','output_dir'):
        value=data[key]
        if key=='wd_dir' and value is None:
            continue
        if not isinstance(value,str) or not value.strip() or len(value)>4000 or any(ord(c)<32 for c in value):
            raise ValueError(key+'の保存先を確認してください。')
        resolved=Path(value).expanduser()
        if not resolved.is_absolute():resolved=path.parent/resolved
        if key=='wd_dir' and not all((resolved/name).is_file() for name in ('model.onnx','selected_tags.csv')):
            raise ValueError('WD保存先にはmodel.onnxとselected_tags.csvが必要です。')
        if key=='output_dir' and resolved.exists() and not resolved.is_dir():
            raise ValueError('出力先はフォルダーを指定してください。')
    return data


class ConfigEditor:
    def __init__(self,path,overrides=()):
        self.path=Path(path).resolve()
        self.overrides=list(overrides)
        self.lock=threading.Lock()

    def _read(self):
        raw=self.path.read_bytes() if self.path.exists() else b''
        data=json.loads(raw.decode('utf-8-sig')) if raw else {}
        if not isinstance(data,dict) or set(data)-set(DEFAULTS):
            raise ValueError('設定ファイルに未対応の項目があります。ファイルで確認してください。')
        merged={**copy.deepcopy(DEFAULTS),**data}
        # Do not return URL credentials or unknown fields to the browser.
        for url in [merged['ollama_url'],merged['comfy_url'],*merged.get('ollama_urls',[])]:
            if not isinstance(url,str):raise ValueError('設定ファイルのURL形式を確認してください。')
            parsed=urlsplit(url)
            if parsed.username or parsed.password or parsed.query:
                raise ValueError('認証情報を含む接続先は画面から編集できません。')
        merged['model']=validate_analysis_model(merged['model'])
        return raw,merged,hashlib.sha256(raw).hexdigest()

    def read(self):
        with self.lock:
            _,data,revision=self._read()
        return dict(settings=data,revision=revision,overrides=self.overrides)

    def _review(self,data,revision):
        raw,old,current=self._read()
        if revision != current:raise ConfigConflict('設定ファイルが変更されています。読み込み直してください。')
        checked=validate(data,self.path)
        changes=[dict(key=key,before=old[key],after=checked[key]) for key in DEFAULTS if old[key]!=checked[key]]
        token=hashlib.sha256((revision+json.dumps(checked,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()
        return raw,checked,changes,token

    def review(self,data,revision):
        with self.lock:
            _,_,changes,token=self._review(data,revision)
        return dict(changes=changes,confirmation=token,restart_required=True)

    def save(self,data,revision,confirmation):
        with self.lock:
            raw,checked,changes,token=self._review(data,revision)
            if token!=confirmation:raise ConfigConflict('変更内容を再確認してください。')
            if not changes:return dict(saved=False,restart_required=False)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            backup=None
            if self.path.exists():
                stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                backup=self.path.with_name(self.path.name+'.backup-'+stamp+'-'+uuid.uuid4().hex[:8])
                descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(descriptor,'wb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
            temporary=self.path.with_name(self.path.name+'.tmp-'+uuid.uuid4().hex)
            try:
                descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:
                    json.dump(checked,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
                # Detect external edits made while the backup was being created.
                current=self.path.read_bytes() if self.path.exists() else b''
                if hashlib.sha256(current).hexdigest()!=revision:
                    raise ConfigConflict('保存中に設定ファイルが変更されました。読み込み直してください。')
                temporary.replace(self.path)
            finally:
                if temporary.exists():temporary.unlink()
            return dict(saved=True,restart_required=True,backup=backup.name if backup else None)
