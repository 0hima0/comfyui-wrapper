"""Image analysis and workflow composition, independent of Flask and persistence."""
from comfyui_wrapper.analysis import wd_tagger
from comfyui_wrapper.workflows import builders
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.prompts import prompt_rules
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.workflows import sdxl_options
from comfyui_wrapper.workflows import person_workflow
from comfyui_wrapper.analysis import analysis_pool
from comfyui_wrapper.prompts import person_prompts


def analyze_references(references, settings, wd_dir, ollama_url, progress):
    bindings=settings.get('lora_assignments')
    if bindings is None:
        bindings=person_prompts.assignments(settings['loras'],[ref.id for ref in references],settings.get('preserve_people',False))
    shared_loras=person_prompts.global_loras(bindings)
    positive_override=', '.join(filter(None,[settings['additional_positive']]+[row['trigger'] for row in shared_loras]))
    reference_reports, wd_conflicts, context = [], [], []
    for reference in references:
        extracted, scores = '', []
        if settings['use_wd']:
            progress(f'画像{reference.id}のWDタグを抽出しています…', 'analysis')
            extracted, scores = wd_tagger.wd_tags(reference.image, wd_dir, settings['threshold'])
        filtered, removed = prompt_rules.filter_candidates(extracted,positive_override,settings['additional_negative'])
        if len(references)>1:
            removed=[dict(item,reference_id=reference.id) for item in removed]
        wd_conflicts.extend(removed)
        reference_reports.append(dict(reference.describe(),candidate_tags=filtered,
            original_candidate_tags=extracted,wd_predictions=scores))
        context.append(dict(id=reference.id,label=f'画像{reference.id}',role=reference.role,candidate_wd_tags=filtered))
    # Keep legacy single-image fields, while reporting every reference separately.
    predictions=reference_reports[0]['wd_predictions'] if reference_reports else []
    tags=reference_reports[0]['candidate_tags'] if len(references)==1 else ''
    raw_tags=', '.join(row['original_candidate_tags'] for row in reference_reports if row['original_candidate_tags'])
    progress('Qwen3-VLで画像を解析しています…（数分かかる場合があります）' if references else '指示とプロンプトから生成内容を組み立てています…', 'analysis')
    analysis_images=[reference.image for reference in references]
    instruction = settings['instruction']
    if settings.get('preserve_people'):
        instruction += ('\nPERSON PRESERVATION MODE: Each reference contains one different person. Place every person '
                        'once, left to right in reference order, in one shared scene. Your positive must ONLY describe '
                        'the number of people, shared scene, action, lighting and composition. Exclude all clothing, '
                        'hair, face, body, person-specific attributes: separate region prompts supply these. '
                        'Use ONE continuous shared background and consistent lighting and perspective. '
                        'Never describe separate panels, split-screen, collage, borders or independent backdrops. '
                        'Do not combine or exchange people. Reference roles cannot change the left-to-right allocation.')
    keep_alive=settings.get('ollama_keep_alive',0)
    def scene(endpoint):
        return generate.analyze(None if settings.get('preserve_people') else (analysis_images[0] if len(analysis_images)==1 else analysis_images or None), instruction, '' if settings.get('preserve_people') else tags,
                                endpoint, settings['analysis_model'], settings['target'],
                                ui_positive=positive_override,ui_negative=settings['additional_negative'],profile=settings['profile'],
                                references=[dict(row,candidate_wd_tags='') for row in context] if settings.get('preserve_people') else context,keep_alive=keep_alive,scene_only=bool(settings.get('preserve_people')))
    def person(index, endpoint):
        reference=references[index]
        return generate.analyze(reference.image,
            'Describe ONLY the single visible person, including hairstyle, face, clothing, colours, accessories '
            'and footwear. Preserve their visible outfit without inventing hidden details. Exclude background, '
            'other people, lighting and camera framing. This is a region prompt for exactly one person. '
            'Use concise English tags; never borrow attributes from other references.',
            reference_reports[index]['candidate_tags'],endpoint,settings['analysis_model'],settings['target'],
            profile=settings['profile'],keep_alive=keep_alive)
    tasks=[('共通場面',scene)]
    if settings.get('preserve_people'):
        tasks.extend((f'画像{ref.id}の人物・服装',lambda endpoint,i=i:person(i,endpoint))
                     for i,ref in enumerate(references))
    endpoints=settings.get('ollama_urls') or []
    if endpoints:
        outputs,execution=analysis_pool.run(tasks,endpoints,lambda message:progress(message,'analysis'))
    else:
        outputs=[]
        for label,call in tasks:
            progress(label+'を解析しています…','analysis')
            outputs.append(call(ollama_url))
        execution=dict(mode='serial',endpoints=[ollama_url])
    result=outputs[0]
    people=[]
    for index,person_result in enumerate(outputs[1:]):
        reference=references[index]
        local_loras=[row for row in bindings if row['reference_id']==reference.id]
        local_positive=', '.join(filter(None,[person_prompts.appearance(person_result['positive'])]+[row['trigger'] for row in local_loras]))
        people.append(dict(reference_id=reference.id, filename=reference.filename, positive=local_positive,
                           loras=local_loras,uncertainties_ja=person_result['uncertainties_ja'],region_index=index))
    analysis_prompts = {key: result[key] for key in ('positive','negative')}
    progress('最終Promptを組み立てています…', 'compose')
    result, generated_conflicts = prompt_rules.merge_prompts(result,positive_override,settings['additional_negative'])
    if settings.get('preserve_people'):
        for key, terms in (('positive', ['single continuous scene', 'shared background', 'consistent lighting', 'consistent perspective']),
                           ('negative', ['split screen', 'diptych', 'triptych', 'collage', 'panel borders', 'vertical divider'])):
            existing = prompt_rules.tokens(result[key])
            result[key] = ', '.join([result[key]] + [term for term in terms if term not in existing])
    if settings.get('preserve_people'):
        result=person_prompts.enforce_count(result,len(references),people)
    result, rating = generate.apply_rating(result,settings['rating'],settings['target'],predictions)
    if settings['rating']=='auto' and references:
        rating['reference_id']=references[0].id
    if settings['use_quality_tags'] and settings['profile']=='animagine4':
        for tag in ('masterpiece','high score','great score','absurdres'):
            if tag not in prompt_rules.tokens(result['positive']) and tag not in prompt_rules.tokens(result['negative']):
                result['positive']+=', '+tag
    return dict(result=result, people=people, analysis_execution=execution, lora_assignments=bindings, analysis_prompts=analysis_prompts, rating=rating,
                reference_images=reference_reports, wd_predictions=predictions, candidate_tags=tags,
                additional_prompts={key: settings['additional_'+key] for key in ('positive','negative')},
                prompt_conflicts={'removed_wd_tags': wd_conflicts, 'removed_generated_tags': generated_conflicts,
                                  'original_candidate_tags': raw_tags, 'priority': 'UI prompts'})


def build_workflow(result, settings, anima_template):
    if settings['target'] == 'anima':
        template = builders.load_anima_template(anima_template)
        workflow = builders.patch_anima(template, result, settings['width'],
                                        settings['height'], settings['seed'], settings['checkpoint'])
    else:
        workflow = builders.animagine_workflow(result, settings['width'], settings['height'],
                                                settings['seed'], settings['checkpoint'])
    if settings['generation_effective']:
        sampler=next(n for n in workflow['nodes'] if n['type']=='KSampler')
        names=['seed','control_after_generate','steps','cfg','sampler_name','scheduler','denoise']
        for key,value in settings['generation_effective'].items():
            sampler['widgets_values'][names.index(key)]=value
            sampler['widgets_values_named'][key]=value
    if settings['target']!='anima':
        bindings=settings.get('lora_assignments')
        if bindings is None:
            bindings=person_prompts.assignments(settings['loras'],[row['reference_id'] for row in settings.get('person_references',[])],settings.get('preserve_people',False))
        workflow=sdxl_options.extend_workflow(workflow,person_prompts.global_loras(bindings),settings['clip_skip'])
    if settings.get('preserve_people'):
        workflow = person_workflow.extend(workflow, settings['person_references'], settings['person_models'],
                                          settings['width'], settings['height'])
    if settings['execute']:
        workflow = comfy_client.prepare(workflow)
    return workflow


def analysis_report(analysis, settings):
    report = dict(analysis)
    if settings.get('batch_sequence'):report['batch_sequence']=settings['batch_sequence']
    report.update({key: settings[key] for key in
        ('instruction','target','seed','width','height','checkpoint','use_wd','execute',
         'profile','loras','clip_skip','use_quality_tags','model_family','input_images')})
    report.update(model=settings['analysis_model'],
                  wd_threshold=settings['threshold'] if settings['use_wd'] else None,
                  wd_model='SmilingWolf/wd-eva02-large-tagger-v3' if settings['use_wd'] else None,
                  wd_predictions_source='reference_image' if analysis['reference_images'] else None,
                  wd_reference_id=analysis['reference_images'][0]['id'] if analysis['reference_images'] else None,
                  generation_settings=settings['generation_effective'],
                  reference_mode='regional_ipadapter' if settings.get('preserve_people') else ('combined_prompt' if analysis['reference_images'] else 'text_only'),
                  person_preservation=dict(enabled=bool(settings.get('preserve_people')),
                      placement='reference_order_left_to_right',
                      references=settings.get('person_references',[]), models=settings.get('person_models',{}),
                      blending=dict(version=person_workflow.BLEND_VERSION,
                          overlap_per_side=person_workflow.overlap_pixels(settings['width'], len(analysis.get('people',[])))
                              if settings.get('preserve_people') else 0,
                          conditioning_area='default', adapter_weight=person_workflow.ADAPTER_WEIGHT,
                          adapter_start_at=person_workflow.ADAPTER_START, adapter_end_at=person_workflow.ADAPTER_END)))
    return report
