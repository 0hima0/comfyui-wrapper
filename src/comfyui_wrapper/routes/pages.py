"""Pages HTTP routes; endpoints remain compatible with earlier releases."""
import os
from datetime import datetime, timezone, timedelta
from flask import abort, jsonify, render_template, url_for
from comfyui_wrapper.generation.reference_images import MAX_IMAGES
from comfyui_wrapper.app_metadata import BASE, RELEASE

def register(app, services):
    wd_dir = services.runtime.wd_dir
    batches = services.batches

    @app.context_processor
    def gallery_retention_policy():
        return dict(gallery_retention_days=services.runtime.gallery_retention_days)

    @app.get('/')
    def index():
        return render_template('index.html', wd_available=bool(wd_dir), manager_open=False, max_reference_images=MAX_IMAGES)

    @app.get('/system')
    def system_page():
        return render_template('system.html', initial_tab='preflight')

    @app.get('/preflight')
    def preflight_page():
        return render_template('system.html', initial_tab='preflight')

    @app.get('/api/version')
    def version_info():
        return jsonify(release=RELEASE,app_directory=str(BASE),pid=os.getpid(),
            lora_samples_api=any(rule.rule=='/api/lora-samples/names' for rule in app.url_map.iter_rules()),
            lora_samples_form='id="managed-sample-files"' in app.jinja_env.get_template('lora_manager.html').render(manager_open=True))

    @app.get('/loras')
    def lora_page():
        return render_template('index.html', wd_available=bool(wd_dir), manager_open=True, max_reference_images=MAX_IMAGES)

    @app.get('/storage')
    def storage_page():
        return render_template('system.html', initial_tab='storage')

    @app.get('/gallery')
    def gallery_page():
        return render_template('gallery.html')

    @app.get('/batches')
    def batch_list_page():
        items=batches.all()
        labels={'running':'連続生成中','review':'選別待ち','cancelled':'停止済み','interrupted':'中断・選別待ち','error':'エラー・選別待ち'}
        for item in items:
            item['display_state']=labels.get(item['state'],'選別待ち')
            records,_=services.history.image_page(limit=3,batch_id=item['batch_id'])
            preview=records[0] if records else {}
            item['checkpoint']=item.get('checkpoint') or preview.get('settings',{}).get('checkpoint') or 'モデル未記録'
            outputs=[(record['job_id'],name) for record in records for name in record.get('images',[])][:3]
            item['preview_urls']=[url_for('gallery_thumbnail',job_id=job,name=name) for job,name in outputs]
            item['preview_url']=item['preview_urls'][0] if outputs else None
            item['range_labels']=[]
            for value in item.get('plan',{}).get('ranges',[]):
                field=value.get('field')
                if field in ('cfg','steps'):
                    label=field.upper() if field=='cfg' else 'Steps'
                elif field=='threshold':
                    label='WD Taggerのしきい値'
                else:
                    index=value.get('lora',0)
                    label=f"LoRA {index+1} " + ('MODEL強度' if field=='strength_model' else 'CLIP強度')
                item['range_labels'].append(dict(label=label,start=value.get('start'),end=value.get('end')))
            try:
                started=datetime.fromisoformat(item['created_at'])
                if started.tzinfo is None:started=started.replace(tzinfo=timezone.utc)
                item['display_time']=started.astimezone(timezone(timedelta(hours=9))).strftime('%Y/%m/%d %H:%M:%S（日本時間）')
            except (ValueError,TypeError,KeyError):item['display_time']='日時未記録'
        return render_template('batches.html',batches=items)

    @app.get('/batch/<batch_id>')
    def batch_page(batch_id):
        if batches.get(batch_id) is None:abort(404)
        return render_template('gallery.html',temporary_batch=batch_id)
