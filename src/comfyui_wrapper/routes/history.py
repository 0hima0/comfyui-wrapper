"""History HTTP routes; endpoints remain compatible with earlier releases."""
import io
import json
from flask import abort, jsonify, send_file, request
from comfyui_wrapper.generation.reference_images import saved_references

def register(app, services):
    history = services.history
    get_job = services.runner.get_job

    @app.get('/api/history')
    def list_history():
        records=history.recoverable() if request.args.get('recoverable')=='1' else history.latest()
        return jsonify(items=[{key:record.get(key) for key in
            ('job_id','created_at','finished_at','state','message','settings','prompt_id')} for record in records])

    @app.get('/api/history/<job_id>')
    def history_detail(job_id):
        record=get_job(job_id)
        if record is None:
            abort(404)
        return jsonify(job_id=job_id,**record)

    @app.get('/api/history/<job_id>/restore')
    def history_restore(job_id):
        record=history.get(job_id)
        if record is None:
            abort(404)
        settings=record.get('settings',{})
        fields={key:settings.get(key) for key in ('analysis_model','target','checkpoint','execute','width','height',
            'seed','use_wd','threshold','rating','instruction','tags','additional_positive','additional_negative',
            'profile','clip_skip','use_quality_tags','preserve_people')}
        fields['analysis_model'] = services.runtime.analysis_model
        fields['preserve_people'] = bool(settings.get('preserve_people'))
        fields.pop('tags', None)
        generation={key:value for key,value in record.get('generation_settings',{}).items()
                    if key in ('steps','cfg','sampler_name','scheduler','denoise')}
        return jsonify(fields=fields,generation_settings=generation,loras=settings.get('loras',[]),
                       reference_filename=(settings.get('input_image') or {}).get('filename',''),
                       reference_images=saved_references(settings))

    @app.get('/api/history/<job_id>/settings')
    def history_settings(job_id):
        record=history.get(job_id)
        if record is None:
            abort(404)
        return send_file(io.BytesIO(json.dumps(dict(job_id=job_id,**record),ensure_ascii=False,indent=2).encode('utf-8')),
                         mimetype='application/json',as_attachment=True,download_name=f'settings_{job_id}.json')
