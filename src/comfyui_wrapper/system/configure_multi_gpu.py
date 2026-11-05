"""Enable two Ollama endpoints in an existing config, retaining other settings."""
import argparse
from comfyui_wrapper.app_metadata import BASE
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from comfyui_wrapper.settings.app_config import load_config


def configure(path):
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('既存のconfig.jsonを指定してください。')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    load_config(path)
    data.update(ollama_urls=['http://127.0.0.1:11434','http://127.0.0.1:11435'],ollama_keep_alive='10m')
    backup=path.with_name(path.name+'.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    temporary=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    shutil.copy2(path,backup)
    try:
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        shutil.copymode(path,temporary)
        load_config(temporary)
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()
    return backup


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=BASE/'config.json')
    args=parser.parse_args(argv)
    try:backup=configure(args.config)
    except (ValueError,OSError) as error:parser.error(str(error))
    print('設定を更新しました。バックアップ: '+str(backup))
    print('解析先: 127.0.0.1:11434 / 127.0.0.1:11435、モデル保持: 10分')
    print('各OllamaのGPU指定とComfyUIのGPU 2指定を完了してからWebUIを再起動してください。')


if __name__=='__main__':
    main()
