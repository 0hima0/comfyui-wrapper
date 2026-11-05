"""Jobs HTTP routes; endpoints remain compatible with earlier releases."""
from flask import abort, jsonify, request, send_file, url_for
from PIL import Image, UnidentifiedImageError
from comfyui_wrapper.generation.submission import GenerationBusy
from comfyui_wrapper.workflows import person_workflow
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.generation.reference_images import load_references
from comfyui_wrapper.app_metadata import FILES
from comfyui_wrapper.infrastructure.http_support import require_ui_request
from comfyui_wrapper.generation.submission_settings import normalize
from comfyui_wrapper.generation import job_archive

def register(app, services):
    root = services.runtime.root
    comfy_url = services.runtime.comfy_url
    get_job = services.runner.get_job
    checkpoints = services.catalog.checkpoints

    @app.post('/api/jobs')
    def submit():
        # Browser requests use a custom header and same origin; no cross-origin CORS access.
        require_ui_request()
        request_id=request.headers.get('X-Request-ID')
        if request_id is not None:
            if len(request_id)!=32 or any(c not in '0123456789abcdef' for c in request_id):
                return jsonify(error='受付IDが不正です。'),400
            receipt=services.runner.submission_receipt(request_id)
            if receipt:return jsonify(**receipt),202
        try:
            settings, raw_seed, batch_plan = normalize(request.form, services.runtime, services.catalog, len(request.files.getlist('image')))
            if settings['execute']:
                choices = checkpoints(settings['target'])
                if choices['source'] != 'comfyui':
                    raise ValueError('画像生成にはComfyUIへの接続が必要です。起動と接続先を確認してください。')
                if settings['checkpoint'] not in choices['names']:
                    raise ValueError('選択したモデルがComfyUIにありません。一覧を更新してください。')
                if settings['loras']:
                    info=comfy_client.api(comfy_url,'/object_info/LoraLoader',timeout=5)
                    available=info['LoraLoader']['input']['required']['lora_name'][0]
                    if any(row['name'] not in available for row in settings['loras']):raise ValueError('選択したLoRAがComfyUIにありません')
            if settings['preserve_people']:
                family = settings['model_family']['family']
                adapter = person_workflow.adapter_name(family)
                # Export without a server is allowed; actual execution checks installed nodes/models first.
                settings['person_models'] = (person_workflow.resolve_models(comfy_url, family, require_hooks=any(row.get('scope','auto')!='global' for row in settings['loras'])) if settings['execute'] else
                                 dict(adapter=adapter, vision=person_workflow.VISION))
            references = load_references(request.files.getlist('image'), request.form.get('reference_info'))
        except (ValueError, TypeError, OverflowError, OSError, KeyError, comfy_client.ComfyError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            return jsonify(error=str(error) or '画像を読み込めませんでした。'), 400
        try:
            reply = services.runner.submit(references, settings, raw_seed, batch_plan,
                reuse_id=request.form.get('reuse_job_id', ''),
                final_positive=request.form.get('final_positive'),
                final_negative=request.form.get('final_negative'),request_id=request_id)
        except GenerationBusy as error:
            return jsonify(error=str(error)), 409
        except (ValueError, OSError, KeyError, TypeError) as error:
            return jsonify(error=str(error)), 400
        return jsonify(**reply), 202

    @app.post('/api/jobs/<job_id>/cancel')
    def cancel_job(job_id):
        require_ui_request()
        try:
            cancelled = services.runner.cancel(job_id)
        except KeyError:
            abort(404)
        return jsonify(cancel_requested=cancelled), 202 if cancelled else 200

    @app.get('/api/jobs/<job_id>')
    def status(job_id):
        job=get_job(job_id)
        if job is None:
            abort(404)
        if job.get('artifacts_ready') and job['state'] != 'running':
            names = list(FILES)
            if (root / job_id / 'workflow_api.json').is_file():
                names.append('workflow_api.json')
            names.extend(job.get('images',[]))
            job['zip_ready'] = job_archive.available(root / job_id)
            job['downloads'] = {name: url_for('download', job_id=job_id, name=name) for name in names
                                if (root / job_id / name).is_file() and not (root / job_id / name).is_symlink()
                                and (name != 'results.zip' or job['zip_ready'])}
        return jsonify(job_id=job_id,**job)

    @app.post('/api/jobs/<job_id>/archive')
    def rebuild_archive(job_id):
        require_ui_request()
        try:
            services.runner.rebuild_archive(job_id)
        except KeyError:
            abort(404)
        except ValueError as error:
            return jsonify(error=str(error)), 409
        return status(job_id)

    @app.post('/api/jobs/<job_id>/reconcile')
    def reconcile_job(job_id):
        require_ui_request()
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or type(data.get('import_images',False)) is not bool:
            return jsonify(error='取り込み指定が不正です。'),400
        try:
            result=services.runner.reconcile(job_id,data.get('import_images',False))
        except KeyError:
            abort(404)
        except ValueError as error:
            return jsonify(error=str(error)),409
        except (OSError,comfy_client.ComfyError):
            app.logger.exception('ComfyUI result reconciliation failed: %s',job_id)
            return jsonify(error='照合・取り込みに失敗しました。保存済み画像は保持しています。再確認してください。'),503
        return jsonify(result)

    @app.get('/download/<job_id>/<name>')
    def download(job_id, name):
        if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            abort(404)
        job=get_job(job_id)
        ready = job and job.get('artifacts_ready') and job['state'] != 'running'
        allowed = list(FILES) + ['workflow_api.json'] + (job.get('images',[]) if job else [])
        if not ready or name not in allowed or not (root / job_id / name).is_file():
            abort(404)
        path = root / job_id / name
        if (root / job_id).is_symlink() or path.is_symlink() or path.resolve().parent != root / job_id:
            abort(404)
        if name == 'results.zip' and not job_archive.available(root / job_id):
            abort(404)
        return send_file(root / job_id / name, as_attachment=request.args.get('inline') != '1', download_name=name)
