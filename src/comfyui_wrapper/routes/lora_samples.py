"""User-uploaded reference samples attached to a LoRA, independent of generation inputs."""
import io
import uuid
from flask import Blueprint, abort, jsonify, request, send_file, url_for
from PIL import Image, UnidentifiedImageError
from comfyui_wrapper.infrastructure.http_support import require_ui_request

MAX_BYTES=5*1024*1024
FORMATS={'PNG':('png','image/png'),'JPEG':('jpg','image/jpeg'),'WEBP':('webp','image/webp')}


def register_lora_samples(app,store,root,thumbnails):
    bp=Blueprint('lora_samples',__name__,url_prefix='/api/lora-samples')
    directory=root/'lora-samples'

    def name_argument():
        name=request.values.get('name','').strip()
        if not name or len(name)>1024 or '\x00' in name:abort(400,description='LoRAを選択してください。')
        return name

    def describe(row):
        return dict(id=row['id'],filename=row['filename'],width=row['width'],height=row['height'],
            image_url=url_for('lora_samples.image',sample_id=row['id']),
            thumbnail_url=url_for('lora_samples.thumbnail',sample_id=row['id']))

    def source(sample_id):
        row=store.sample(sample_id)
        if row is None:abort(404)
        path=directory/(row['id']+'.'+row['extension'])
        if not path.is_file():abort(404)
        return row,path

    @bp.get('/names')
    def names():return jsonify(names=store.sample_names())

    @bp.get('')
    def listing():return jsonify(items=[describe(row) for row in store.samples(name_argument())])

    @bp.post('')
    def upload():
        require_ui_request();name=name_argument();files=request.files.getlist('images')
        if not 1<=len(files)<=6:return jsonify(error='画像を1〜6枚選択してください。'),400
        rows=[];staged=[];committed=False
        try:
            for file in files:
                raw=file.read(MAX_BYTES+1)
                if not raw or len(raw)>MAX_BYTES:raise ValueError('画像は1枚5MB以内にしてください。')
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format not in FORMATS:raise ValueError('PNG・JPEG・WebPを選択してください。')
                        if image.width*image.height>24000000:raise ValueError('画像は1枚2400万画素以内にしてください。')
                        extension,mimetype=FORMATS[image.format];width,height=image.size;image.verify()
                except (OSError,SyntaxError) as error:
                    raise ValueError('画像を読み込めませんでした。') from error
                sample_id=uuid.uuid4().hex
                filename=(file.filename or 'sample').replace('\\','/').split('/')[-1][:200]
                directory.mkdir(parents=True,exist_ok=True)
                path=directory/(sample_id+'.'+extension);staged.append(path);path.write_bytes(raw)
                rows.append(dict(id=sample_id,filename=filename,extension=extension,mimetype=mimetype,width=width,height=height))
            store.add_samples(name,rows);committed=True
            return jsonify(items=[describe(row) for row in store.samples(name)]),201
        except (ValueError,UnidentifiedImageError) as error:
            return jsonify(error=str(error)),400
        except Image.DecompressionBombError:
            return jsonify(error='画像は1枚2400万画素以内にしてください。'),400
        except OSError:
            app.logger.exception('LoRA sample upload failed')
            return jsonify(error='画像を保存できませんでした。保存先の空き容量・権限を確認してください。'),500
        finally:
            if not committed:
                for path in staged:path.unlink(missing_ok=True)

    @bp.get('/<sample_id>/image')
    def image(sample_id):
        row,path=source(sample_id)
        return send_file(path,mimetype=row['mimetype'],as_attachment=False,download_name=row['filename'])

    @bp.get('/<sample_id>/thumbnail')
    def thumbnail(sample_id):
        _,path=source(sample_id)
        try:preview=thumbnails.get(path)
        except (OSError,ValueError,Image.DecompressionBombError):abort(400)
        response=send_file(preview,mimetype='image/jpeg',conditional=True,max_age=86400)
        response.cache_control.public=False;response.cache_control.private=True
        return response

    @bp.delete('/<sample_id>')
    def remove(sample_id):
        require_ui_request();row,path=source(sample_id)
        thumbnails.path_for(path).unlink(missing_ok=True)
        path.unlink();store.delete_sample(sample_id)
        return jsonify(items=[describe(item) for item in store.samples(row['name'])])

    app.register_blueprint(bp)
