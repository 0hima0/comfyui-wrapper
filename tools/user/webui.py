"""Command entry point; implementation lives in comfyui_wrapper."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'internal'))
import _bootstrap  # Enable imports from the repository src directory.
from comfyui_wrapper.webui import ANALYSIS_MODEL, BASE, FILES, RELEASE, create_app, main, parse_args

if __name__ == '__main__':
    raise SystemExit(main())
