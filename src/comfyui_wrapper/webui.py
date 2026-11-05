"""Browser UI entry point. Run: python webui.py --host 0.0.0.0"""
import argparse
import logging
import sys
from pathlib import Path
from flask import Flask
from comfyui_wrapper.settings.app_config import load_config, validate_ollama_urls, validate_keep_alive, validate_analysis_model
from comfyui_wrapper.app_metadata import BASE, ANALYSIS_MODEL, FILES, RELEASE
from comfyui_wrapper.app_services import create_services
from comfyui_wrapper.infrastructure.http_support import install_http_support
from comfyui_wrapper.routes.lora_samples import register_lora_samples
from comfyui_wrapper.routes import register_routes
from comfyui_wrapper.infrastructure.instance_lock import InstanceLock
from comfyui_wrapper.settings.config_editor import ConfigEditor


def create_app(output_dir=None, ollama_url='http://127.0.0.1:11434',
               model=ANALYSIS_MODEL, wd_dir=None, comfy_url='http://127.0.0.1:8188',
               checkpoint_families=None, lora_folders=None, ollama_urls=None, ollama_keep_alive=0, checkpoint_lora_folders=None, gallery_retention_days=10):
    app = Flask(__name__, template_folder=str(BASE/'web/templates'),
                static_folder=str(BASE/'web/static'), static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024
    services = create_services(Path(output_dir or BASE/'web-results').resolve(), app.logger,
        ollama_url=ollama_url, comfy_url=comfy_url, wd_dir=wd_dir,
        checkpoint_families=checkpoint_families, lora_folders=lora_folders,
        ollama_urls=ollama_urls, ollama_keep_alive=ollama_keep_alive, analysis_model=model, checkpoint_lora_folders=checkpoint_lora_folders, gallery_retention_days=gallery_retention_days)
    app.extensions.update(app_services=services, storage_usage=services.storage,
        batch_store=services.batches, gallery_cleanup=services.cleanup,
        image_jobs=services.runner.records, generation_lock=services.runner.busy)
    install_http_support(app)
    register_lora_samples(app, services.lora_store, services.runtime.root, services.thumbnails)
    register_routes(app, services)
    return app


def parse_args(argv=None):
    if argv is None:
        argv=sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=BASE/'config.json')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--ollama-url')
    parser.add_argument('--ollama-urls',nargs='+',help='画像解析先を複数指定。各Ollamaを別GPUで起動してください')
    parser.add_argument('--ollama-keep-alive')
    parser.add_argument('--model')
    parser.add_argument('--comfy-url')
    parser.add_argument('--wd-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    args.config_overrides=[name.replace('-', '_') for name in ('host','port','ollama-url','ollama-urls','ollama-keep-alive','model','comfy-url','wd-dir','output-dir') if any(value=='--'+name or value.startswith('--'+name+'=') for value in argv)]
    if not args.config.exists() and any(v=='--config' or v.startswith('--config=') for v in argv):
        parser.error('指定された設定ファイルがありません')
    try:
        config=load_config(args.config)
    except (OSError,ValueError,TypeError) as error:
        parser.error(str(error))
    for name,value in config.items():
        if getattr(args,name,None) is None:
            setattr(args,name,value)
    try:
        args.model=validate_analysis_model(args.model)
        args.ollama_urls=validate_ollama_urls(args.ollama_urls)
        args.ollama_keep_alive=validate_keep_alive(args.ollama_keep_alive)
    except ValueError as error:
        parser.error(str(error))
    if args.wd_dir and not all((args.wd_dir / name).is_file() for name in ('model.onnx','selected_tags.csv')):
        parser.error('--wd-dirにはmodel.onnxとselected_tags.csvが必要です。')
    return args


def main():
    args=parse_args()
    logging.basicConfig(level=logging.INFO)
    from waitress import serve
    with InstanceLock(args.output_dir or BASE/'web-results'):
        app = create_app(args.output_dir, args.ollama_url, args.model, args.wd_dir, args.comfy_url,
                         checkpoint_families=args.checkpoint_families, lora_folders=args.lora_folders, checkpoint_lora_folders=args.checkpoint_lora_folders,
                         ollama_urls=args.ollama_urls,ollama_keep_alive=args.ollama_keep_alive, gallery_retention_days=args.gallery_retention_days)
        app.extensions['config_editor']=ConfigEditor(args.config,args.config_overrides)
        app.extensions['gallery_cleanup'].start()
        print(f'WebUI: http://{args.host}:{args.port} （別PCからはサーバーのIPアドレスで接続）', flush=True)
        serve(app, host=args.host, port=args.port, threads=4, max_request_body_size=25*1024*1024)


if __name__ == '__main__':
    main()
