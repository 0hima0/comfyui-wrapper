"""Batches HTTP routes; endpoints remain compatible with earlier releases."""
from flask import abort, jsonify, request, url_for
from comfyui_wrapper.infrastructure.http_support import require_ui_request

def register(app, services):
    batches = services.batches
    storage = services.storage
    get_job = services.runner.get_job

    @app.get('/api/generation-state')
    def generation_state():
        active=services.runner.active_batch()
        return jsonify(active_batch=active)

    @app.get('/api/batches')
    def list_batches():
        return jsonify(items=batches.all())

    @app.get('/api/batches/<batch_id>')
    def batch_status(batch_id):
        batch=batches.get(batch_id)
        if batch is None:abort(404)
        current=get_job(batch.get('current_job',''))
        return jsonify(**batch,active_job=current if current and current['state']=='running' else None)

    @app.put('/api/batches/<batch_id>/name')
    def rename_batch(batch_id):
        require_ui_request()
        data=request.get_json(silent=True)
        try:
            name=batches.rename(batch_id,data.get('name') if isinstance(data,dict) else None)
        except KeyError:abort(404)
        except ValueError as error:return jsonify(error=str(error)),400
        return jsonify(name=name)

    @app.post('/api/batches/<batch_id>/<action>')
    def batch_action(batch_id,action):
        require_ui_request()
        if action=='cancel':
            try:
                cancelled=services.runner.cancel_batch(batch_id)
            except KeyError:
                abort(404)
            return jsonify(cancel_requested=cancelled)
        if action!='finalize':abort(404)
        data=request.get_json(silent=True)
        try:
            if not isinstance(data,dict):raise ValueError('入力形式が不正です。')
            kept=batches.finalize(batch_id,data.get('selected'))
        except KeyError:return jsonify(error='連続生成レビューが見つかりません。'),404
        except ValueError as error:return jsonify(error=str(error)),409
        except OSError:
            app.logger.exception('Batch finalization failed')
            return jsonify(error='選別を確定できませんでした。保存先の空き容量と権限を確認してください。'),500
        storage.invalidate()
        return jsonify(kept=kept,redirect=url_for('gallery_page'))
