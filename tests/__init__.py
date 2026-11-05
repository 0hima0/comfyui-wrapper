"""Offline regression tests for ComfyUI Wrapper."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for directory in ('user', 'dev', 'internal'):
    sys.path.insert(0, str(ROOT / 'tools' / directory))
import _bootstrap