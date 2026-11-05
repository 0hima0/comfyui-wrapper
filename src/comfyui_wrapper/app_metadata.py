"""Shared paths and release identity; independent of the web application."""
from pathlib import Path
BASE = Path(__file__).resolve().parents[2]
# Backward-compatible default; each application uses Runtime.analysis_model.
ANALYSIS_MODEL = 'qwen3-vl:8b-instruct'
from comfyui_wrapper.versioning import parse_version
RELEASE = (BASE / 'VERSION').read_text(encoding='utf-8').strip()
parse_version(RELEASE)
FILES = ('workflow.json', 'analysis.json', 'positive.txt', 'negative.txt', 'results.zip')
