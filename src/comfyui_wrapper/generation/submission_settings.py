"""Shared settings normalization for execution and preflight, without network or image I/O."""
import json
import secrets
from comfyui_wrapper.workflows import sdxl_options
from comfyui_wrapper.models import model_families
from comfyui_wrapper.app_metadata import ANALYSIS_MODEL


def normalize(form, runtime, catalog, image_count, *, check_wd=True):
    wd_dir = runtime.wd_dir
    lora_folders = runtime.lora_folders
    ollama_urls = runtime.ollama_urls
    ollama_keep_alive = runtime.ollama_keep_alive
    default_checkpoint = catalog.default_checkpoint
    classify = catalog.classify
    target = form.get('target', 'anima')
    analysis_model=getattr(runtime,'analysis_model',ANALYSIS_MODEL)
    if target not in ('anima', 'animagine'):
        raise ValueError('生成モデルを選択してください。')
    width, height = (int(form.get(key, '1024')) for key in ('width', 'height'))
    if any(n < 256 or n > 2048 or n % 64 for n in (width, height)):
        raise ValueError('幅と高さは256〜2048の64の倍数を指定してください。')
    raw_seed = form.get('seed', '').strip()
    seed = int(raw_seed) if raw_seed else secrets.randbelow(2**53)
    if not 0 <= seed <= 2**53-1:
        raise ValueError('シードは0〜9007199254740991です。')
    threshold = float(form.get('threshold', '0.35'))
    if not 0 <= threshold <= 1:
        raise ValueError('しきい値は0〜1です。')
    use_wd = form.get('use_wd') == 'on' and image_count > 0
    rating = form.get('rating','none')
    if rating not in ('none','auto','safe','sensitive','nsfw','explicit'):
        raise ValueError('レーティングタグを選択してください。')
    if image_count == 0 and rating == 'auto':
        rating = 'none'
    if rating == 'auto' and not use_wd:
        raise ValueError('WD自動判定を使う場合はWD Taggerをオンにしてください。')
    if check_wd and use_wd and not wd_dir:
        raise ValueError('WDのモデルフォルダーを起動時に指定してください。')
    instruction = form.get('instruction', '').strip()
    if image_count == 0 and not (instruction or form.get('additional_positive', '').strip()):
        raise ValueError('参考画像がない場合は、指示または追加Positive Promptを入力してください。')
    instruction = instruction or ('追加Positive Promptをもとに画像を生成する' if image_count == 0 else '画像の見た目を参考にした画像を生成したい')
    tags = ''
    checkpoint = form.get('checkpoint', default_checkpoint(target)).strip()
    classification = classify(target,checkpoint)
    selection = form.get('profile','auto')
    profile=sdxl_options.resolve_profile(target,checkpoint,selection)
    if selection == 'auto' and classification['family'] == 'sd15':
        profile = 'sd15'
    defaults=sdxl_options.PROFILES[profile]
    loras=sdxl_options.validate_loras(json.loads(form.get('loras','[]')))
    if any(not model_families.allowed_lora(target,checkpoint,classification['family'],row['name'],lora_folders,getattr(runtime,'checkpoint_lora_folders',{})) for row in loras):
        raise ValueError('生成モデルに許可されたLoRAフォルダーではありません。LoRAを解除するか、アプリ設定のモデルとLoRAフォルダーの対応を確認してください。')
    clip_skip=int(form.get('clip_skip',str(defaults['clip_skip'])))
    if not 0<=clip_skip<=24:raise ValueError('CLIP skipは0〜24です')
    if target=='anima' and (loras or clip_skip):raise ValueError('今回のLoRA／CLIP skip機能はSDXL用です')
    use_quality_tags=form.get('use_quality_tags')=='on'
    execute = form.get('execute') == 'on'
    batch_plan=json.loads(form['batch_plan']) if 'batch_plan' in form else None
    restored_generation=json.loads(form.get('restored_generation','{}'))
    effective=sdxl_options.generation_settings(profile,form,restored_generation)
    additional_positive = form.get('additional_positive','').strip()
    additional_negative = form.get('additional_negative','').strip()
    if len(additional_positive)>8000 or len(additional_negative)>8000:
        raise ValueError('追加プロンプトはそれぞれ8000文字以内にしてください。')
    if len(instruction) > 8000 or len(tags) > 20000 or not 1 <= len(checkpoint) <= 300:
        raise ValueError('入力が長すぎるか、チェックポイント名が空です。')
    preserve_people = form.get('preserve_people') == 'on' and image_count > 1
    person_models = {}
    settings = dict(target=target, width=width, height=height, seed=seed,
                    threshold=threshold, use_wd=use_wd, instruction=instruction,
                    tags=tags, checkpoint=checkpoint, execute=execute, rating=rating,
                    additional_positive=additional_positive, additional_negative=additional_negative)
    settings.update(preserve_people=preserve_people, person_models=person_models,
                    ollama_urls=ollama_urls,ollama_keep_alive=ollama_keep_alive,lora_assignments=[])
    settings['analysis_model']=analysis_model
    settings['restored_generation']=restored_generation
    settings.update(profile=profile,loras=loras,clip_skip=clip_skip,use_quality_tags=use_quality_tags,generation_effective=effective)
    settings['model_family'] = classification
    return settings, raw_seed, batch_plan
