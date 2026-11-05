"""Run offline Python and browser-logic regression tests from any directory."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'internal'))
import _bootstrap  # Enable imports from the repository src directory.
import argparse
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    suites = parser.add_mutually_exclusive_group()
    suites.add_argument('--python-only', action='store_true')
    suites.add_argument('--frontend-only', action='store_true')
    suites.add_argument('--browser-only', action='store_true', help='Run real-page Chromium integration tests (requires playwright)')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args(argv)
    if args.browser_only:
        os.environ['WRAPPER_BROWSER_TESTS'] = '1'
        suite = unittest.defaultTestLoader.discover(str(ROOT/'tests/browser'), top_level_dir=str(ROOT))
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    ok = True
    if not args.frontend_only:
        sys.path.insert(0, str(ROOT))
        suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), top_level_dir=str(ROOT))
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
        ok = result.wasSuccessful()
    if not args.python_only:
        node = shutil.which('node')
        if node is None:
            print('Node.js is required for frontend tests; use --python-only for Python tests.', file=sys.stderr)
            return 1
        files = sorted((ROOT/'tests/frontend').glob('test_*.cjs'))
        print(f'Running {len(files)} frontend test files.', flush=True)
        for path in files:
            try:
                result = subprocess.run([node, str(path)], cwd=ROOT, timeout=60)
                ok = result.returncode == 0 and ok
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f'{path.name}: {error}', file=sys.stderr)
                ok = False
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
