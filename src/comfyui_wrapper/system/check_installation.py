"""Inspect a Git checkout and its running server without fetching or updating."""
import argparse
from comfyui_wrapper.app_metadata import BASE
import json
import subprocess
from pathlib import Path
import urllib.request
import urllib.error


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=BASE)
    parser.add_argument('--url',default='http://127.0.0.1:7860')
    args=parser.parse_args(argv);root=args.directory.resolve();ok=True;release=None
    print('確認する配置先:',root)
    try:
        if not (root/'.git').is_dir():
            raise ValueError('Not a normal Git clone')
        def git(*arguments):
            result=subprocess.run(['git','-C',str(root),*arguments],capture_output=True,timeout=15)
            if result.returncode:raise ValueError('Git inspection failed')
            return result.stdout.decode('utf-8').strip()
        if Path(git('rev-parse','--show-toplevel')).resolve()!=root:
            raise ValueError('Not the repository root')
        release=(root/'VERSION').read_text(encoding='utf-8').strip()
        print('配置ファイルの版:',release)
        print('配置コミット:',git('rev-parse','HEAD'))
        changes=git('status','--porcelain','--untracked-files=no')
        flags=git('ls-files','-v').splitlines()
        if any(line and (line[0]=='S' or line[0].islower()) for line in flags):
            ok=False;print('疎なチェックアウト・assume-unchangedは更新対象外です。')
        elif changes:
            ok=False;print('追跡ファイルにローカル変更があります。')
        else:print('追跡ファイル: HEADと一致（リモートの最新版確認は行いません）')
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        print('Git cloneを確認できません。導入・移行手順を確認してください。')
        return 1
    try:
        with urllib.request.urlopen(args.url.rstrip('/')+'/api/version',timeout=5) as response:running=json.load(response)
        print('動作中の版:',running.get('release'));print('動作中の配置先:',running.get('app_directory'));print('プロセスID:',running.get('pid'))
        same_path=Path(running.get('app_directory','')).resolve()==root
        if running.get('release')!=release or not same_path:
            ok=False;print('配置先または版が一致しません。起動コマンド・サービスのExecStartと再起動先を確認してください。')
        if not running.get('lora_samples_api') or not running.get('lora_samples_form'):
            ok=False;print('サンプル画像APIまたは画面が未更新です。アプリ全体を更新してWebUIを再起動してください。')
        with urllib.request.urlopen(args.url.rstrip('/')+'/api/lora-samples/names',timeout=5) as response:
            names=json.load(response)
        if not isinstance(names.get('names'),list):raise ValueError('unexpected response')
        print('サンプル画像API: 利用可能')
    except urllib.error.HTTPError as error:
        ok=False;print('サーバー確認: HTTP',error.code,'（古いWebUIまたは別の接続先の可能性があります）')
    except (OSError,ValueError,AttributeError):
        ok=False;print('サーバーに接続できないか、想定外の応答です。起動状態とURLを確認してください。')
    print('確認結果:', '正常' if ok else '更新・起動先の確認が必要')
    return 0 if ok else 1


if __name__=='__main__':raise SystemExit(main())
