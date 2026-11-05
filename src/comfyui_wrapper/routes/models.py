"""Models HTTP routes; endpoints remain compatible with earlier releases."""
from flask import jsonify, request
from comfyui_wrapper.system import preflight
from comfyui_wrapper.settings.settings_presets import validate as validate_preset
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.workflows import sdxl_options
from comfyui_wrapper.models import model_families
from comfyui_wrapper.generation.reference_images import MAX_IMAGES
from comfyui_wrapper.app_metadata import BASE
from comfyui_wrapper.infrastructure.http_support import require_ui_request
from comfyui_wrapper.generation.submission_settings import normalize
import json

def register(app, services):
    wd_dir = services.runtime.wd_dir
    ollama_url = services.runtime.ollama_url
    comfy_url = services.runtime.comfy_url
    ollama_urls = services.runtime.ollama_urls
    lora_folders = services.runtime.lora_folders
    history = services.history
    checkpoints = services.catalog.checkpoints
    classify = services.catalog.classify

    @app.get('/api/checkpoints')
    def list_checkpoints():
        target = request.args.get('target', 'anima')
        if target not in ('anima', 'animagine'):
            return jsonify(error='生成モデルを選択してください。'), 400
        return jsonify(checkpoints(target))

    @app.get('/api/models')
    def list_models():
        models, warnings = [], []
        for target in ('anima','animagine'):
            data = checkpoints(target)
            if data['source'] != 'comfyui':
                warnings.append(data['warning'])
                continue
            for name in data['names']:
                profile=sdxl_options.resolve_profile(target,name)
                classification = classify(target, name)
                if classification['family'] == 'sd15':
                    profile = 'sd15'
                models.append(dict(name=name,target=target,
                    profile=profile,defaults=sdxl_options.PROFILES[profile],
                    **classification,
                    label='['+classification['family_label']+'] '+name+' （'+sdxl_options.PROFILES[profile]['label']+'）'))
        return jsonify(models=models, warning=' '.join(dict.fromkeys(warnings)))

    @app.get('/api/generation-options')
    def generation_options():
        result=dict(loras=[],loras_available=False,samplers=[],schedulers=[],profiles=sdxl_options.PROFILES,warnings=[])
        for kind in ('LoraLoader','KSampler'):
            try:
                info=comfy_client.api(comfy_url,'/object_info/'+kind,timeout=5)[kind]['input']['required']
                if kind=='LoraLoader':
                    names=info['lora_name'][0]
                    if not isinstance(names,list) or any(not isinstance(name,str) for name in names):raise TypeError()
                    result.update(loras=names,loras_available=True)
                else:result.update(samplers=info['sampler_name'][0],schedulers=info['scheduler'][0])
            except (comfy_client.ComfyError,KeyError,TypeError,IndexError):
                result['warnings'].append(kind+'の設定一覧を取得できませんでした。')
        result['lora_options'] = [dict(name=name, folders=['/'.join(model_families.parts(name)[:i]) for i in range(1,len(model_families.parts(name)))], family=model_families.folder_family(name,lora_folders),
            family_label=model_families.LABELS[model_families.folder_family(name,lora_folders)])
            for name in result['loras']]
        return jsonify(result)

    @app.get('/api/analysis-models')
    def analysis_models():
        return jsonify(models=[services.runtime.analysis_model], default=services.runtime.analysis_model, warning='')

    @app.post('/api/preflight')
    def preflight_check():
        require_ui_request()
        data=request.get_json(silent=True)
        try:
            if not isinstance(data,dict):raise ValueError('確認する設定が不正です。')
            checked=validate_preset(dict(name='preflight',fields=data.get('fields'),loras=data.get('loras',[])))
            fields=checked['fields']
            ids=data.get('reference_ids',[])
            if not isinstance(ids,list) or len(ids)>MAX_IMAGES or any(type(i) is not int or not 1<=i<=9999 for i in ids) or len(set(ids))!=len(ids):raise ValueError('参考画像の番号が不正です。')
            form={key: ('on' if value else '') if type(value) is bool else str(value) for key,value in fields.items()}
            form['loras']=json.dumps(checked['loras'])
            if 'restored_generation' in data:
                form['restored_generation']=json.dumps(data['restored_generation'])
            settings, _, _=normalize(form,services.runtime,services.catalog,len(ids),check_wd=False)
            reuse_id=data.get('reuse_job_id')
            if reuse_id:
                source=history.get(reuse_id) if isinstance(reuse_id,str) else None
                if not source or not source.get('artifacts_ready') or source.get('state')=='running':raise ValueError('再利用する解析元が見つかりません。再解析してください。')
            result=preflight.check(settings,dict(ollama_url=ollama_url,ollama_urls=ollama_urls,comfy_url=comfy_url,wd_dir=wd_dir),
                BASE/'workflows/anima_template.json',ids,bool(reuse_id))
            return jsonify(result)
        except (ValueError,KeyError,TypeError) as error:return jsonify(error=str(error)),400
