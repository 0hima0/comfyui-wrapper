"""Region-scoped image and text conditioning for one person per reference."""
import copy
import io
import json
import uuid
import urllib.request
from PIL import Image, ImageOps
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.infrastructure import job_control
from comfyui_wrapper.prompts import person_prompts

REQUIRED = ('IPAdapterAdvanced', 'IPAdapterModelLoader', 'CLIPVisionLoader',
            'LoadImage', 'SolidMask', 'FeatherMask', 'MaskComposite', 'ConditioningSetMask', 'ConditioningCombine')
BLEND_VERSION = 'scene_priority_v3'
ADAPTER_WEIGHT = .65
ADAPTER_START = .15
ADAPTER_END = .85
HOOK_NODES = ('CreateHookLora','SetClipHooks')


def overlap_pixels(width, count):
    # A narrow transition around each boundary, away from the subject centres.
    return max(8, min(64, width // (count * 8)))


VISION = 'CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors'


def adapter_name(family):
    if family not in ('sd15', 'sdxl', 'illustrious'):
        raise ValueError('人物を維持する組み合わせはSD1.5／SDXL／Illustriousに対応します。Anima・未判定モデルは未対応です。')
    return 'ip-adapter-plus_sd15.safetensors' if family == 'sd15' else 'ip-adapter-plus_sdxl_vit-h.safetensors'


def resolve_models(url, family, require_hooks=False, info=None):
    wanted = adapter_name(family)
    if info is None:info = comfy_client.api(url, '/object_info')
    missing = [name for name in (REQUIRED+HOOK_NODES if require_hooks else REQUIRED) if name not in info]
    if missing:
        hint = ('CreateHookLora／SetClipHooksはComfyUI標準のノードです。ComfyUI本体を更新し、再起動してください。'
                if any(name in HOOK_NODES for name in missing) else '同梱のdocs/ADDITIONAL_SETUP.mdの導入手順を確認してください。')
        raise ValueError('人物維持に必要なComfyUIノードがありません: '+', '.join(missing)+'。'+hint)
    def choose(kind, field, filename):
        names = info[kind]['input']['required'][field][0]
        matches = [name for name in names if name.replace('\\', '/').split('/')[-1] == filename]
        if not matches:
            raise ValueError('人物維持用モデルがありません: '+filename+'。docs/ADDITIONAL_SETUP.mdを確認してください。')
        return sorted(matches)[0]
    return dict(adapter=choose('IPAdapterModelLoader', 'ipadapter_file', wanted),
                vision=choose('CLIPVisionLoader', 'clip_name', VISION))


def reference_png(image):
    # Keep the entire outfit visible to CLIP Vision's square centre crop.
    with image.convert('RGBA') as rgba:
        with Image.new('RGBA', rgba.size, 'white') as background:
            background.alpha_composite(rgba)
            rgb = background.convert('RGB')
    try:
        with ImageOps.pad(rgb, (1024,1024), color='white') as square:
            output = io.BytesIO(); square.save(output, format='PNG')
            return output.getvalue()
    finally:
        rgb.close()


def upload(url, raw, subfolder, name):
    job_control.check()
    boundary = 'LLMPC'+uuid.uuid4().hex
    parts = []
    for key, value in (('type','input'), ('subfolder',subfolder), ('overwrite','false')):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: image/png\r\n\r\n'.encode(),
              raw, f'\r\n--{boundary}--\r\n'.encode()]
    request = urllib.request.Request(url.rstrip('/')+'/upload/image', data=b''.join(parts),
                                    headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request, timeout=60) as response:
        saved = json.load(response)
    job_control.check()
    if saved.get('type') != 'input' or saved.get('subfolder') != subfolder or saved.get('name') != name:
        raise ValueError('ComfyUIの参考画像アップロード先を確認できませんでした。再実行してください。')
    return subfolder+'/'+name


def extend(workflow, people, models, width, height):
    """Chain masked adapters after LoRA; combine individually masked text conditions."""
    if not 2 <= len(people) <= 4:
        raise ValueError('人物維持は2〜4枚、各画像に1人の人物を指定してください。')
    result = copy.deepcopy(workflow)
    nodes = {n['id']:n for n in result['nodes']}
    edges = [tuple(link[1:]) for link in result['links']]
    sampler = next(n for n in nodes.values() if n['type']=='KSampler')
    def source(node, field):
        slot = next(i for i,item in enumerate(node['inputs']) if item['name']==field)
        edge = next(e for e in edges if e[2:4]==(node['id'],slot))
        return edge[:2], slot
    model, model_slot = source(sampler, 'model')
    positive, positive_slot = source(sampler, 'positive')
    negative, negative_slot = source(sampler, 'negative')
    scene_prompt=nodes[positive[0]]['widgets_values_named']['text']
    negative_prompt=nodes[negative[0]]['widgets_values_named']['text']
    text_node = nodes[positive[0]]
    clip, _ = source(text_node, 'clip')
    def add(kind, values, inputs, outputs, x, y):
        nid=max(nodes)+1
        n=dict(id=nid,type=kind,pos=[x,y],size=[300,200],flags={},order=len(nodes),mode=0,
               inputs=[dict(name=name,type=typ,link=None) for name,typ in inputs],
               outputs=[dict(name=typ,type=typ,links=[]) for typ in outputs],
               properties={'Node name for S&R':kind},widgets_values=list(values.values()),widgets_values_named=values)
        nodes[nid]=n;result['nodes'].append(n)
        return nid
    def wire(src,dst,slot,typ): edges.append((*src,dst,slot,typ))
    ipa=add('IPAdapterModelLoader',dict(ipadapter_file=models['adapter']),[],['IPADAPTER'],0,1000)
    vision=add('CLIPVisionLoader',dict(clip_name=models['vision']),[],['CLIP_VISION'],0,1250)
    fade = overlap_pixels(width, len(people))
    for index, person in enumerate(people):
        y=1000+index*700
        # Widths aligned to latent pixels; final band covers any remainder.
        left=(width*index//len(people)//8)*8
        right=(width*(index+1)//len(people)//8)*8 if index+1<len(people) else width
        start = max(0, left-fade)
        end = min(width, right+fade)
        image=add('LoadImage',dict(image=person['comfy_image']),[],['IMAGE','MASK'],350,y)
        blank=add('SolidMask',dict(value=0.,width=width,height=height),[],['MASK'],350,y+240)
        band=add('SolidMask',dict(value=1.,width=end-start,height=height),[],['MASK'],350,y+460)
        softened=add('FeatherMask',dict(left=2*fade if index else 0,top=0,
                      right=2*fade if index+1<len(people) else 0,bottom=0),
                      [('mask','MASK')],['MASK'],700,y+460)
        wire((band,0),softened,0,'MASK')
        mask=add('MaskComposite',dict(x=start,y=0,operation='add'),[('destination','MASK'),('source','MASK')],['MASK'],700,y+240)
        wire((blank,0),mask,0,'MASK');wire((softened,0),mask,1,'MASK')
        adapted=add('IPAdapterAdvanced',dict(weight=ADAPTER_WEIGHT,weight_type='linear',combine_embeds='concat',
                    start_at=ADAPTER_START,end_at=ADAPTER_END,embeds_scaling='V only'),
                    [('model','MODEL'),('ipadapter','IPADAPTER'),('image','IMAGE'),('attn_mask','MASK'),('clip_vision','CLIP_VISION')],['MODEL'],1050,y)
        for src,slot,typ in ((model,0,'MODEL'),((ipa,0),1,'IPADAPTER'),((image,0),2,'IMAGE'),((mask,0),3,'MASK'),((vision,0),4,'CLIP_VISION')):
            wire(src,adapted,slot,typ)
        model=(adapted,0)
        local_clip=clip
        hook=None
        for row in person.get('loras',[]):
            hook_inputs=[('prev_hooks','HOOKS')] if hook is not None else []
            new_hook=add('CreateHookLora',dict(lora_name=row['name'],strength_model=row['strength_model'],strength_clip=row['strength_clip']),
                         hook_inputs,['HOOKS'],1750,y)
            if hook is not None:wire((hook,0),new_hook,0,'HOOKS')
            hook=new_hook
        if hook is not None:
            hooked_clip=add('SetClipHooks',dict(apply_to_conds=True,schedule_clip=False),
                            [('clip','CLIP'),('hooks','HOOKS')],['CLIP'],2100,y)
            wire(clip,hooked_clip,0,'CLIP');wire((hook,0),hooked_clip,1,'HOOKS')
            local_clip=(hooked_clip,0)
        text=add('CLIPTextEncode',dict(text=person_prompts.regional_text(scene_prompt,person['positive'],index,len(people))),[('clip','CLIP')],['CONDITIONING'],700,y+460)
        wire(local_clip,text,0,'CLIP')
        scoped=add('ConditioningSetMask',dict(strength=1.,set_cond_area='default'),
                   [('conditioning','CONDITIONING'),('mask','MASK')],['CONDITIONING'],1050,y+240)
        wire((text,0),scoped,0,'CONDITIONING');wire((mask,0),scoped,1,'MASK')
        combined=add('ConditioningCombine',{},[('conditioning_1','CONDITIONING'),('conditioning_2','CONDITIONING')],['CONDITIONING'],1400,y+240)
        wire(positive,combined,0,'CONDITIONING');wire((scoped,0),combined,1,'CONDITIONING')
        positive=(combined,0)
        if hook is not None:
            neg_text=add('CLIPTextEncode',dict(text=person_prompts.regional_negative(negative_prompt)),
                         [('clip','CLIP')],['CONDITIONING'],1750,y+240)
            wire(local_clip,neg_text,0,'CLIP')
            neg_scoped=add('ConditioningSetMask',dict(strength=1.,set_cond_area='default'),
                           [('conditioning','CONDITIONING'),('mask','MASK')],['CONDITIONING'],2100,y+240)
            wire((neg_text,0),neg_scoped,0,'CONDITIONING');wire((mask,0),neg_scoped,1,'MASK')
            neg_combined=add('ConditioningCombine',{},[('conditioning_1','CONDITIONING'),('conditioning_2','CONDITIONING')],['CONDITIONING'],2450,y+240)
            wire(negative,neg_combined,0,'CONDITIONING');wire((neg_scoped,0),neg_combined,1,'CONDITIONING')
            negative=(neg_combined,0)
    edges=[e for e in edges if not(e[2]==sampler['id'] and e[3] in (model_slot,positive_slot,negative_slot))]
    wire(model,sampler['id'],model_slot,'MODEL');wire(positive,sampler['id'],positive_slot,'CONDITIONING');wire(negative,sampler['id'],negative_slot,'CONDITIONING')
    for n in nodes.values():
        for out in n['outputs']: out['links']=[]
    result['links']=[]
    for number,(src,slot,dst,dslot,typ) in enumerate(edges,1):
        result['links'].append([number,src,slot,dst,dslot,typ])
        nodes[src]['outputs'][slot]['links'].append(number)
        nodes[dst]['inputs'][dslot]['link']=number
    result.update(last_node_id=max(nodes),last_link_id=len(edges))
    return result
