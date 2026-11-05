"""Model profiles and standard-node SDXL LoRA/CLIP wiring."""
import copy
import re
import math

PROFILES={
    'anima':dict(label='Anima',steps=30,cfg=4,sampler_name='er_sde',scheduler='simple',clip_skip=0),
    'animagine31':dict(label='Animagine XL 3.1',steps=28,cfg=7,sampler_name='euler_ancestral',scheduler='normal',clip_skip=0),
    'animagine4':dict(label='Animagine XL 4.0 / Opt',steps=28,cfg=5,sampler_name='euler_ancestral',scheduler='normal',clip_skip=0),
    'wai17':dict(label='WAI Illustrious v17（確認用初期値）',steps=28,cfg=5,sampler_name='euler_ancestral',scheduler='normal',clip_skip=0),
    'sdxl':dict(label='汎用SDXL',steps=28,cfg=7,sampler_name='euler_ancestral',scheduler='normal',clip_skip=0),
    'sd15':dict(label='SD1.5',steps=28,cfg=7,sampler_name='euler_ancestral',scheduler='normal',clip_skip=0),
}


def resolve_profile(target,checkpoint,selection='auto'):
    if target=='anima':
        if selection not in ('auto','anima'):
            raise ValueError('AnimaにはSDXLプロファイルを適用できません')
        return 'anima'
    if selection!='auto':
        if selection not in PROFILES or selection=='anima':raise ValueError('SDXLプロファイルが不正です')
        return selection
    name=re.sub(r'[^a-z0-9]','',checkpoint.lower())
    if 'wai' in name and 'v17' in name:return 'wai17'
    if 'animagine' in name and ('40' in name or 'v4' in name):return 'animagine4'
    if 'animagine' in name and ('31' in name or 'v3' in name):return 'animagine31'
    return 'sdxl'


def validate_loras(value):
    if not isinstance(value,list) or len(value)>3:raise ValueError('LoRAは最大3個です')
    result=[]
    for row in value:
        if not isinstance(row,dict):raise ValueError('LoRA設定が不正です')
        name=row.get('name','')
        if not isinstance(name,str) or not 1<=len(name)<=300:raise ValueError('LoRA名が不正です')
        entry={'name':name}
        for key in ('strength_model','strength_clip'):
            strength=row.get(key,.7)
            if type(strength) not in (int,float) or not math.isfinite(strength) or not -2<=strength<=2:
                raise ValueError('LoRA強度は-2〜2で指定してください')
            entry[key]=strength
        trigger=row.get('trigger','')
        if not isinstance(trigger,str):raise ValueError('LoRAトリガーが不正です')
        trigger=trigger.strip()
        if len(trigger)>2000:raise ValueError('LoRAトリガーは2000文字以内です')
        entry['trigger']=trigger
        if 'scope' in row:
            scope=row['scope']
            if not isinstance(scope,str) or not (scope in ('auto','global') or re.fullmatch(r'image:[1-9][0-9]{0,3}',scope)):
                raise ValueError('LoRAの適用先が不正です')
            entry['scope']=scope
        result.append(entry)
    return result


def extend_workflow(workflow,loras,clip_skip):
    """Insert LoRA chain, then CLIPSetLastLayer before BOTH text encoders."""
    result=copy.deepcopy(workflow)
    nodes={node['id']:node for node in result['nodes']}
    loader=next(node for node in result['nodes'] if node['type']=='CheckpointLoaderSimple')
    model_source,clip_source=(loader['id'],0),(loader['id'],1)
    edges=[tuple(link[1:]) for link in result['links']]
    original=list(edges)
    next_id=max(nodes)+1
    def add(kind,names,values,inputs,outputs):
        nonlocal next_id
        node={'id':next_id,'type':kind,'pos':[350+(next_id-8)*330,700],'size':[300,180],
              'flags':{},'order':len(nodes),'mode':0,
              'inputs':[{'name':name,'type':typ,'link':None} for name,typ in inputs],
              'outputs':[{'name':name,'type':typ,'links':[]} for name,typ in outputs],
              'properties':{'Node name for S&R':kind},'widgets_values':values,
              'widgets_values_named':dict(zip(names,values))}
        nodes[next_id]=node;result['nodes'].append(node);next_id+=1
        return node['id']
    for row in loras:
        nid=add('LoraLoader',['lora_name','strength_model','strength_clip'],
                [row['name'],row['strength_model'],row['strength_clip']],
                [('model','MODEL'),('clip','CLIP')],[('MODEL','MODEL'),('CLIP','CLIP')])
        edges.extend([(model_source[0],model_source[1],nid,0,'MODEL'),(clip_source[0],clip_source[1],nid,1,'CLIP')])
        model_source,clip_source=(nid,0),(nid,1)
    if clip_skip:
        nid=add('CLIPSetLastLayer',['stop_at_clip_layer'],[-clip_skip],[('clip','CLIP')],[('CLIP','CLIP')])
        edges.append((clip_source[0],clip_source[1],nid,0,'CLIP'))
        clip_source=(nid,0)
    for index,edge in enumerate(original):
        src,slot,dst,dslot,kind=edge
        if src==loader['id'] and slot==0:
            edges[index]=(*model_source,dst,dslot,kind)
        elif src==loader['id'] and slot==1:
            edges[index]=(*clip_source,dst,dslot,kind)
    for node in nodes.values():
        for output in node['outputs']:output['links']=[]
    result['links']=[]
    for number,(src,slot,dst,dslot,kind) in enumerate(edges,1):
        result['links'].append([number,src,slot,dst,dslot,kind])
        nodes[src]['outputs'][slot]['links'].append(number)
        nodes[dst]['inputs'][dslot]['link']=number
    result['last_node_id']=max(nodes)
    result['last_link_id']=len(edges)
    return result


_NO_RESTORED_SETTINGS = object()


def generation_settings(profile, overrides, restored_generation=_NO_RESTORED_SETTINGS):
    """Validate restored values, then apply explicit UI overrides in a fixed order."""
    defaults = PROFILES[profile]
    if restored_generation is _NO_RESTORED_SETTINGS:
        restored_generation = {}
    if not isinstance(restored_generation,dict) or set(restored_generation)-{'steps','cfg','sampler_name','scheduler','denoise'}:
        raise ValueError('復元する生成設定が不正です。')
    for key,value in restored_generation.items():
        if key=='steps' and (type(value) is not int or not 1<=value<=10000):
            raise ValueError('復元するStepsが不正です。')
        if key in ('cfg','denoise') and (type(value) not in (int,float) or not 0<=value<=(100 if key=='cfg' else 1)):
            raise ValueError('復元する生成設定の数値が不正です。')
        if key in ('sampler_name','scheduler') and (not isinstance(value,str) or not 1<=len(value)<=100):
            raise ValueError('復元するサンプラー設定が不正です。')
    effective={key:defaults[key] for key in ('steps','cfg','sampler_name','scheduler')}
    effective.update(denoise=1,**{k:v for k,v in restored_generation.items() if k!='denoise'})
    if 'denoise' in restored_generation:effective['denoise']=restored_generation['denoise']
    for key,cast in [('steps',int),('cfg',float),('denoise',float),('sampler_name',str),('scheduler',str)]:
        if key in overrides:effective[key]=cast(overrides[key])
    if not 1<=effective['steps']<=10000 or not 0<=effective['cfg']<=100 or not 0<=effective['denoise']<=1:
        raise ValueError('Steps／CFG／Denoiseの値が不正です')
    if not all(0<len(effective[key])<=100 for key in ('sampler_name','scheduler')):
        raise ValueError('サンプラー設定が不正です')
    return effective
