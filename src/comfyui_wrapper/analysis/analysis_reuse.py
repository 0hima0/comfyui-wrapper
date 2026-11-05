"""Validate analysis reuse against the exact inputs used for analysis."""
import copy
import hashlib
import json

VERSION = 1
ANALYSIS_FIELDS = ('analysis_model','target','profile','instruction','use_wd',
                   'additional_positive','additional_negative','preserve_people','rating','use_quality_tags')

def fingerprint(references, settings):
    values={key:settings.get(key) for key in ANALYSIS_FIELDS}
    values['threshold']=settings.get('threshold') if settings.get('use_wd') else None
    values['loras']=[{key:row.get(key,'auto' if key=='scope' else '') for key in ('name','trigger','scope')} for row in settings.get('loras',[])]
    values['references']=[]
    for ref in references:
        values['references'].append(dict(id=ref.id,role=ref.role,size=list(ref.image.size),
            pixels=hashlib.sha256(ref.image.tobytes()).hexdigest()))
    raw=json.dumps(values,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()

def restore(report, expected, positive, negative, source):
    if report.get('reuse_version')!=VERSION or report.get('reuse_fingerprint')!=expected:
        raise ValueError('参考画像・指示・タグ設定・LoRA構成が解析時と異なるか、旧版の解析結果です。「解析して生成」で再解析してください。')
    for value in (positive,negative):
        if not isinstance(value,str) or len(value)>64000 or '\x00' in value:
            raise ValueError('最終Promptはそれぞれ64000文字以内で指定してください。')
    if not positive.strip():raise ValueError('Positive promptを入力してください。')
    keys=('result','people','lora_assignments','analysis_prompts','rating','reference_images',
          'wd_predictions','candidate_tags','additional_prompts','prompt_conflicts')
    analysis={key:copy.deepcopy(report[key]) for key in keys if key in report}
    if not isinstance(analysis.get('result'),dict) or not isinstance(analysis.get('reference_images'), list):
        raise ValueError('再利用できる解析結果がありません。再解析してください。')
    analysis['result'].update(positive=positive.strip(),negative=negative.strip())
    analysis['analysis_execution']=dict(mode='reused',source_job_id=source)
    return analysis
