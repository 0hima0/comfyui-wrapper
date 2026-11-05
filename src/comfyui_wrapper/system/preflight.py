"""Read-only dependency checks: never load a model or submit a ComfyUI job."""
import importlib.util
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.workflows import person_workflow
from comfyui_wrapper.prompts import person_prompts
from comfyui_wrapper.generation.generation_pipeline import build_workflow


def check(settings, runtime, template, reference_ids, reuse=False):
    checks=[]
    def add(name,ok,detail):checks.append(dict(name=name,ok=bool(ok),detail=detail))
    add('参考画像',0<=len(reference_ids)<=4,'選択済み：'+str(len(reference_ids))+'枚' if reference_ids else '指示・プロンプトのみで生成します。')
    if reuse:
        add('画像解析',True,'保存済みの解析結果を使うためOllamaへの接続確認を省略します。')
    else:
        endpoints=runtime['ollama_urls'] or [runtime['ollama_url']]
        def ollama(endpoint):
            try:
                with urllib.request.urlopen(endpoint.rstrip('/')+'/api/tags',timeout=5) as response:data=json.load(response)
                names={row.get('name',row.get('model')) for row in data['models']}
                if settings['analysis_model'] not in names:return False,'解析モデル '+settings['analysis_model']+' がありません。Ollamaへ導入してください。'
                return True,'接続と解析モデルを確認しました。'
            except (OSError,ValueError,KeyError,TypeError):return False,'接続またはモデル一覧の取得に失敗しました。Ollamaの起動・接続先を確認してください。'
        with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
            for index,(endpoint,result) in enumerate(zip(endpoints,pool.map(ollama,endpoints))):
                add('Ollama 解析先'+str(index+1),result[0],endpoint+'：'+result[1])
    if settings.get('use_wd') and (not reuse or settings['execute']):
        directory=Path(runtime['wd_dir']) if runtime['wd_dir'] else None
        missing=[name for name in ('model.onnx','selected_tags.csv') if not directory or not (directory/name).is_file()]
        modules=[name for name in ('numpy','onnxruntime') if importlib.util.find_spec(name) is None]
        add('WD Tagger',not missing and not modules,('不足ファイル：'+', '.join(missing)+'。' if missing else '')+
            ('不足パッケージ：'+', '.join(modules)+'。requirements.txtを導入してください。' if modules else '') or 'モデルファイルと必要パッケージを確認しました。')
    if settings['execute']:
        try:
            info=comfy_client.api(runtime['comfy_url'],'/object_info',timeout=5)
            settings=dict(settings)
            if settings.get('preserve_people'):
                settings['person_models']=person_workflow.resolve_models(runtime['comfy_url'],settings['model_family']['family'],
                    require_hooks=any(row.get('scope','auto')!='global' for row in settings['loras']),info=info)
                assignments=person_prompts.assignments(settings['loras'],reference_ids,True)
                settings['lora_assignments']=assignments
                settings['person_references']=[dict(reference_id=ref,positive='one person',region_index=i,
                    comfy_image='preflight-reference.png',loras=[row for row in assignments if row['reference_id']==ref]) for i,ref in enumerate(reference_ids)]
            workflow=build_workflow(dict(positive='scene',negative='text'),settings,template)
            comfy_client.validate(comfy_client.to_api(workflow),info)
            add('ComfyUI・生成モデル・必要ノード',True,'接続先 '+runtime['comfy_url']+' のモデル・LoRA・必要ノード・サンプラー設定を確認しました。')
        except (comfy_client.ComfyError,ValueError,KeyError,TypeError,IndexError,OSError) as error:
            add('ComfyUI・生成モデル・必要ノード',False,str(error)+'。ComfyUIの起動・モデル配置・必要ノードを確認してください。')
    else:add('ComfyUI',True,'画像生成オフのため確認対象外です。')
    return dict(ok=all(row['ok'] for row in checks),checks=checks)
