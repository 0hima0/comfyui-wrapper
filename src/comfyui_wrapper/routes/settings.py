"""Settings HTTP routes; endpoints remain compatible with earlier releases."""
from urllib.parse import urlsplit
from flask import jsonify, request
from comfyui_wrapper.infrastructure.http_support import require_ui_request

def register(app, services):
    presets = services.presets
    lora_store = services.lora_store

    @app.get('/api/lora-triggers')
    def lora_records():
        if request.args.get('summary')=='1':return jsonify(records=lora_store.summaries())
        if 'name' in request.args:
            name=request.args['name']
            if not name or len(name)>1024 or '\x00' in name:return jsonify(error='LoRA名が不正です。'),400
            record=lora_store.get(name)
            return jsonify(records={name:record} if record else {})
        return jsonify(records=lora_store.all())

    @app.route('/api/lora-triggers', methods=['PUT', 'DELETE'])
    def change_lora_record():
        require_ui_request()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='入力形式が不正です。'), 400
        limits = {'name': 1024, 'trigger': 2000, 'url': 2000, 'note': 8000}
        values = {}
        for key, limit in limits.items():
            value = data.get(key, '')
            if not isinstance(value, str) or len(value) > limit or '\x00' in value:
                return jsonify(error='入力が不正か、長すぎます。'), 400
            values[key] = value.strip()
        if not values['name']:
            return jsonify(error='LoRAを選択してください。'), 400
        if values['url']:
            try:
                parsed = urlsplit(values['url'])
                if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                    raise ValueError()
            except ValueError:
                return jsonify(error='配布元URLは有効なhttpまたはhttpsのURLで指定してください。'), 400
        if 'recommended_prompt' in data:
            prompt=data['recommended_prompt']
            if not isinstance(prompt,str) or len(prompt)>8000 or '\x00' in prompt:
                return jsonify(error='推奨プロンプトは8000文字以内で入力してください。'),400
            values['recommended_prompt']=prompt.strip()
        if 'tags' in data:
            from comfyui_wrapper.models.lora_store import validate_tags
            try:values['tags']=validate_tags(data['tags'])
            except ValueError as error:return jsonify(error=str(error)),400
        if request.method == 'DELETE':
            lora_store.delete(values['name'])
        else:
            lora_store.save(**values)
        if request.args.get('summary')=='1':
            return jsonify(records=lora_store.summaries(),record=lora_store.get(values['name']))
        return jsonify(records=lora_store.all())

    @app.route('/api/presets',methods=['GET','POST'])
    @app.route('/api/presets/<preset_id>',methods=['PUT','DELETE'])
    def settings_presets(preset_id=None):
        if request.method=='GET':return jsonify(items=presets.all())
        require_ui_request()
        try:
            if request.method=='DELETE':presets.delete(preset_id)
            else:preset_id=presets.save(request.get_json(silent=True),preset_id)
        except ValueError as error:return jsonify(error=str(error)),400
        except KeyError:return jsonify(error='プリセットが見つかりません。一覧を更新してください。'),404
        return jsonify(id=preset_id,items=presets.all())

    @app.route('/api/instruction-presets',methods=['GET','POST'])
    @app.route('/api/instruction-presets/<instruction_id>',methods=['PUT','DELETE'])
    def instruction_presets(instruction_id=None):
        store=services.instructions
        if request.method=='GET':return jsonify(items=store.all())
        require_ui_request()
        try:
            if request.method=='DELETE':store.delete(instruction_id)
            else:instruction_id=store.save(request.get_json(silent=True),instruction_id)
        except ValueError as error:return jsonify(error=str(error)),400
        except KeyError:return jsonify(error='保存した指示が見つかりません。一覧を更新してください。'),404
        return jsonify(id=instruction_id,items=store.all())
