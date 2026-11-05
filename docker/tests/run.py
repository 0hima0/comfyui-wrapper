"""Run tests against an ephemeral copy; the image and host source remain untouched."""
import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    source=Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='wrapper-tests-') as temporary:
        workspace=Path(temporary)/'workspace'
        shutil.copytree(source,workspace)
        print('Python:',sys.version.split()[0],flush=True)
        subprocess.run(['node','--version'],check=True)
        print('Checking Python and JavaScript syntax...',flush=True)
        try:
            for directory in ('src','scripts','tools','tests','docker/tests'):
                for path in (workspace/directory).rglob('*.py'):
                    ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path.relative_to(workspace)))
            javascript=sorted((workspace/'web/static').glob('*.js'))+sorted((workspace/'tests/frontend').glob('*.cjs'))
            for path in javascript:
                subprocess.run(['node','--check',str(path)],check=True)
        except (SyntaxError,UnicodeError,subprocess.CalledProcessError) as error:
            print('Syntax check failed:',error,file=sys.stderr)
            return 1
        print('Testing isolated source copy; no host files or GPU required.',flush=True)
        return subprocess.run([sys.executable,str(workspace/'tools/dev/run_tests.py'),*sys.argv[1:]],cwd=workspace).returncode


if __name__=='__main__':
    raise SystemExit(main())