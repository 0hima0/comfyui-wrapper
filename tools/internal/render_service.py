"""Render a systemd service for a selected user and installation directory."""
import argparse
import json
import re
from pathlib import Path


def render(template, app_dir, user):
    if not isinstance(user,str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]*[$]?', user):
        raise ValueError('サービス実行ユーザー名が不正です。')
    app_dir=Path(app_dir).resolve()
    if '$' in str(app_dir):
        raise ValueError('サービス配置先にはドル記号を使用できません。')
    def quote(value):
        value=str(value)
        if any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('配置先に制御文字は使用できません。')
        # systemd expands percent specifiers and ExecStart environment variables.
        return json.dumps(value.replace('%','%%').replace('$','$$'),ensure_ascii=False)
    result=template
    for key,value in {'SERVICE_USER':user,'APP_DIR':quote(app_dir),
                      'PYTHON':quote(app_dir/'.venv/bin/python'),
                      'WEBUI':quote(app_dir/'tools/user/webui.py'),'CONFIG':quote(app_dir/'config.json')}.items():
        if key=='APP_DIR':
            # WorkingDirectory is a literal path, not an ExecStart argument.
            value=str(app_dir).replace('%','%%')
        result=result.replace('@'+key+'@',value)
    if re.search(r'@[A-Z_]+@',result):
        raise ValueError('未設定のサービス項目があります。')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir',type=Path,required=True)
    parser.add_argument('--user',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    template=Path(__file__).resolve().parents[2]/'deploy/systemd/comfyui-wrapper.service'
    try:
        result=render(template.read_text(encoding='utf-8'),args.app_dir,args.user)
        args.output.write_text(result,encoding='utf-8',newline='\n')
    except (OSError,ValueError) as error:
        parser.error(str(error))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
