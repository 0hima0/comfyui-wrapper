"""Common browser request validation and response policies."""
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from flask import abort, jsonify, request
from comfyui_wrapper.app_metadata import RELEASE

def require_ui_request():
    """Retain the custom-header and same-origin guard for every write operation."""
    if request.headers.get('X-Requested-With') != 'LLMPC':
        abort(403)
    origin = request.headers.get('Origin')
    if origin and urlsplit(origin).netloc != request.host:
        abort(403)

def install_http_support(app):
    asset_versions = {}
    @app.context_processor
    def application_version():
        return dict(app_version=RELEASE)
    @app.url_defaults
    def version_static_assets(endpoint,values):
        if endpoint!='static' or 'filename' not in values or 'v' in values:return
        try:
            path=Path(app.static_folder)/values['filename']
            stat=path.stat();signature=(stat.st_mtime_ns,stat.st_size)
            cached=asset_versions.get(str(path))
            if cached is None or cached[0]!=signature:
                cached=(signature,hashlib.sha256(path.read_bytes()).hexdigest()[:12])
                asset_versions[str(path)]=cached
            values['v']=cached[1]
        except OSError:
            pass

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.endpoint not in ('gallery_thumbnail','lora_samples.thumbnail') or response.status_code not in (200,304):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-LLMPC-Version'] = RELEASE
        return response

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='画像と入力の合計は25MB以内にしてください。'), 413
