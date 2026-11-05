"""Bounds and validation for the small structured image-analysis response."""
import json
import re

LIMITS = dict(summary_ja=240, positive=1600, negative=400, uncertainties_ja=240)
RETRY_LIMITS = dict(summary_ja=160, positive=1000, negative=240, uncertainties_ja=160)
MAX_STREAM_CHARS = 12000


def schema(limits):
    return dict(type='object', properties={key:dict(type='string', maxLength=limit,
                minLength=1 if key=='positive' else 0) for key,limit in limits.items()},
                required=list(limits), additionalProperties=False)


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError('応答JSONの項目が重複しています')
        result[key]=value
    return result


def parse(content, output_schema):
    result=json.loads(content, object_pairs_hook=_unique_object)
    fields=output_schema['properties']
    if not isinstance(result,dict) or set(result)!=set(fields) or any(not isinstance(result[k],str) for k in fields):
        raise ValueError('応答JSONの必須項目が不正')
    if not result['positive'].strip():
        raise ValueError('Positive promptが空')
    for key,spec in fields.items():
        if len(result[key])>spec['maxLength']:
            raise ValueError('応答項目の文字数上限を超えました: '+key)
    for key in ('positive','negative'):
        tags=[tag.strip().casefold() for tag in re.split(r'[,\n]+',result[key]) if tag.strip()]
        if any(tags.count(tag)>=3 for tag in set(tags)):
            raise ValueError('応答のタグが繰り返されています')
    return result


def stream_guard(content, thinking=''):
    if len(content)+len(thinking)>MAX_STREAM_CHARS:
        return '応答が長すぎるため途中で停止しました'
    # Only long repeated blocks: ordinary repeated short words are legitimate.
    if re.search(r'(.{32,128})\1{3}',content[-1024:],re.DOTALL):
        return '応答の反復を検出して途中で停止しました'
    return ''
