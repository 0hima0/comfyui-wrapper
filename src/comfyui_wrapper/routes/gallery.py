"""Gallery HTTP routes; endpoints remain compatible with earlier releases."""
import sqlite3
from datetime import date,datetime,time,timedelta,timezone
from flask import abort, jsonify, request, send_file, url_for
from PIL import Image
from comfyui_wrapper.gallery.gallery_thumbnails import source_version
from comfyui_wrapper.gallery.gallery_cleanup import DeleteBlocked
from comfyui_wrapper.infrastructure.http_support import require_ui_request

def register(app, services):
    root = services.runtime.root
    history = services.history
    batches = services.batches
    storage = services.storage
    thumbnails = services.thumbnails
    cleanup = services.cleanup
    lock = services.runner.lock

    @app.get('/api/storage-usage')
    def storage_usage():
        refresh=request.args.get('refresh','0')
        if refresh not in ('0','1'):return jsonify(error='更新の指定が不正です。'),400
        try:return jsonify(storage.get(force=refresh=='1'))
        except (OSError,sqlite3.Error):
            app.logger.exception('Storage usage measurement failed')
            return jsonify(error='保存容量を取得できません。しばらくしてから容量を更新してください。'),503

    @app.get('/api/gallery')
    def gallery_images():
        try:
            offset=int(request.args.get('offset','0'))
            if not 0<=offset<=1000000:raise ValueError()
        except ValueError:
            return jsonify(error='表示位置が不正です。'),400
        favorites=request.args.get('favorites','0')
        if favorites not in ('0','1'):
            return jsonify(error='お気に入りの絞り込み指定が不正です。'),400
        batch_id=request.args.get('batch_id')
        if batch_id and batches.get(batch_id) is None:abort(404)
        filters={key:request.args.get(key,'').strip() for key in ('q','model','lora','label','after','before')}
        try:
            if any(len(value)>300 or '\x00' in value for value in filters.values()):raise ValueError()
            for key in ('after','before'):
                if filters[key]:
                    value=date.fromisoformat(filters[key])
                    if key=='before':value+=timedelta(days=1)
                    filters[key]=datetime.combine(value,time(),tzinfo=timezone(timedelta(hours=9))).isoformat()
            if filters['after'] and filters['before'] and filters['after']>=filters['before']:raise ValueError()
        except (ValueError,OverflowError):return jsonify(error='検索条件または期間が不正です。'),400
        records,has_more=history.image_page(offset,favorites_only=favorites=='1',batch_id=batch_id,**({'filters':filters} if any(filters.values()) else {}))
        page_annotations=history.annotations_many(record['job_id'] for record in records)
        items=[]
        for record in records:
            job_id=record['job_id']
            settings=record.get('settings',{})
            annotations=page_annotations.get(job_id,{})
            for name in record.get('images',[]):
                favorite=name in record.get('favorites',[])
                annotation=annotations.get(name,dict(note='',labels=[]))
                if filters['q'] and not record.get('text_match',True) and filters['q'].lower() not in (annotation['note']+' '+' '.join(annotation['labels'])).lower():continue
                if filters['label'] and filters['label'] not in annotations.get(name,{}).get('labels',[]):continue
                if favorites=='1' and not favorite:continue
                if not isinstance(name,str) or '/' in name or '\\' in name:continue
                image_path=(root/job_id/name).resolve()
                if not image_path.is_relative_to(root) or not image_path.is_file():continue
                output=next((row for row in record.get('output_files',[]) if row.get('webui_filename')==name),{})
                items.append(dict(job_id=job_id,filename=name,favorite=favorite,annotation=annotations.get(name,dict(note='',labels=[])),batch_cell=record.get('batch_cell'),
                    batch_index=record.get('batch_index'),threshold=settings.get('threshold'),loras=settings.get('loras',[]),use_wd=settings.get('use_wd',False),
                    protected=bool(record.get('favorites')),image_count=len(record.get('images',[])),
                    delete_url=url_for('gallery_delete',job_id=job_id),
                    favorite_url=url_for('gallery_favorite',job_id=job_id,name=name),created_at=record.get('created_at'),
                    checkpoint=settings.get('checkpoint',''),width=settings.get('width'),height=settings.get('height'),
                    seed=settings.get('seed'),summary=record.get('result',{}).get('summary_ja',''),
                    comfy_filename=output.get('comfy_filename',''),
                    thumbnail_url=url_for('gallery_thumbnail',job_id=job_id,name=name,v=source_version(image_path)),
                    image_url=url_for('download',job_id=job_id,name=name,inline='1'),
                    download_url=url_for('download',job_id=job_id,name=name),
                    restore_url=url_for('index',restore=job_id),
                    settings_url=url_for('history_settings',job_id=job_id)))
        return jsonify(items=items,has_more=has_more,next_offset=offset+len(records))

    @app.put('/api/gallery/<job_id>/<name>/annotation')
    def gallery_annotation(job_id,name):
        require_ui_request()
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='入力形式が不正です。'),400
        note,labels=data.get('note',''),data.get('labels',[])
        if (not isinstance(note,str) or len(note)>4000 or '\x00' in note or not isinstance(labels,list) or len(labels)>20 or
            any(not isinstance(x,str) or not x.strip() or len(x)>40 or '\x00' in x for x in labels)):
            return jsonify(error='メモは4000文字、ラベルは各40文字・20個までです。'),400
        with lock:
            record=history.get(job_id)
            if not record or name not in record.get('images',[]) or not record.get('artifacts_ready'):abort(404)
            if record.get('temporary') or record.get('state')=='running':return jsonify(error='通常ギャラリーに保存後に編集してください。'),409
            source=(root/job_id/name).resolve()
            if '/' in name or '\\' in name or not source.is_relative_to(root) or not source.is_file():abort(404)
            labels=list(dict.fromkeys(x.strip() for x in labels))
            history.annotate(job_id,name,note,labels)
        return jsonify(note=note,labels=labels)

    @app.put('/api/gallery/<job_id>/<name>/favorite')
    def gallery_favorite(job_id,name):
        require_ui_request()
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or type(data.get('favorite')) is not bool:
            return jsonify(error='お気に入りの指定が不正です。'),400
        record=history.get(job_id)
        if record and record.get('temporary'):return jsonify(error='連続生成レビューでは、残す画像を選んで確定してください。'),409
        if not record or not record.get('artifacts_ready') or record.get('state')=='running' or name not in record.get('images',[]):
            return jsonify(error='保存済みの生成画像が見つかりません。'),404
        source=(root/job_id/name).resolve()
        if '/' in name or '\\' in name or not source.is_relative_to(root) or not source.is_file():abort(404)
        with lock:
            # Serialize with deletion and recheck after taking the shared lock.
            if history.get(job_id) is None:abort(404)
            history.set_favorite(job_id,name,data['favorite'])
        storage.invalidate()
        return jsonify(favorite=data['favorite'])

    @app.delete('/api/gallery/<job_id>')
    def gallery_delete(job_id):
        require_ui_request()
        try:cleanup.delete(job_id)
        except KeyError:return jsonify(error='削除する実行が見つかりません。'),404
        except DeleteBlocked as error:return jsonify(error=str(error)),409
        except OSError:
            app.logger.exception('Gallery deletion failed: %s',job_id)
            return jsonify(error='ファイルを削除できませんでした。保存先の権限を確認してください。'),500
        storage.invalidate()
        return jsonify(deleted=True,job_id=job_id)

    @app.post('/api/gallery/bulk-delete')
    def gallery_bulk_delete():
        require_ui_request()
        data=request.get_json(silent=True)
        ids=data.get('job_ids') if isinstance(data,dict) else None
        if (not isinstance(ids,list) or not 1<=len(ids)<=500 or
                any(not isinstance(k,str) or len(k)!=32 or any(c not in '0123456789abcdef' for c in k) for k in ids)):
            return jsonify(error='削除する実行IDを1〜500件指定してください。'),400
        deleted=[];skipped=[]
        for job_id in dict.fromkeys(ids):
            try:cleanup.delete(job_id)
            except KeyError:skipped.append(dict(job_id=job_id,error='実行が見つかりません。'))
            except DeleteBlocked as error:skipped.append(dict(job_id=job_id,error=str(error)))
            except OSError:
                app.logger.exception('Bulk gallery deletion failed: %s',job_id)
                skipped.append(dict(job_id=job_id,error='ファイルを削除できませんでした。保存先の権限を確認してください。'))
            else:deleted.append(job_id)
        if deleted:storage.invalidate()
        return jsonify(deleted=deleted,skipped=skipped)

    @app.get('/gallery/thumbnail/<job_id>/<name>')
    def gallery_thumbnail(job_id,name):
        record=history.get(job_id)
        if not record or not record.get('artifacts_ready') or record.get('state')=='running' or name not in record.get('images',[]):
            abort(404)
        source=(root/job_id/name).resolve()
        if '/' in name or '\\' in name or not source.is_relative_to(root) or not source.is_file():abort(404)
        try:
            target=thumbnails.get(source)
        except (OSError,ValueError,Image.DecompressionBombError):
            return jsonify(error='プレビュー画像を作成できませんでした。'),400
        response=send_file(target,mimetype='image/jpeg',conditional=True,max_age=86400)
        response.cache_control.public=False
        response.cache_control.private=True
        return response
