"""Workflow builders."""
import copy

def set_widgets(node, names, values):
    node['widgets_values'] = values
    node['widgets_values_named'] = dict(zip(names, values))


def patch_anima(template, result, width, height, seed, unet_name=None):
    workflow = copy.deepcopy(template)
    nodes = {node['id']: node for node in workflow['nodes']}
    required = {11: 'CLIPTextEncode', 12: 'CLIPTextEncode', 19: 'KSampler', 28: 'EmptyLatentImage'}
    for key, kind in required.items():
        if nodes.get(key, {}).get('type') != kind:
            raise ValueError('添付Animaテンプレートとノード構成が異なります')
    set_widgets(nodes[11], ['text'], [result['positive']])
    set_widgets(nodes[12], ['text'], [result['negative']])
    set_widgets(nodes[28], ['width', 'height', 'batch_size'], [width, height, 1])
    values = list(nodes[19]['widgets_values'])
    values[0:2] = [seed, 'fixed']
    set_widgets(nodes[19], ['seed', 'control_after_generate', 'steps', 'cfg',
                          'sampler_name', 'scheduler', 'denoise'], values)
    if unet_name is not None:
        if nodes.get(44, {}).get('type') != 'UNETLoader':
            raise ValueError('Animaモデル読み込みノードが見つかりません')
        values = list(nodes[44]['widgets_values'])
        values[0] = unet_name
        set_widgets(nodes[44], ['unet_name', 'weight_dtype'], values)
    return workflow


def animagine_workflow(result, width, height, seed, checkpoint):
    # Standard SDXL graph; deliberately separate from the Anima graph.
    nodes, links = [], []
    def node(n, kind, x, y, names, values, outputs):
        item = {'id': n, 'type': kind, 'pos': [x,y], 'size': [320,180],
                'flags': {}, 'order': n-1, 'mode': 0, 'inputs': [],
                'outputs': [{'name': name, 'type': typ, 'links': []} for name,typ in outputs],
                'properties': {'Node name for S&R': kind}}
        set_widgets(item, names, values)
        nodes.append(item)
        return item
    loader = node(1,'CheckpointLoaderSimple',0,0,['ckpt_name'],[checkpoint],
                  [('MODEL','MODEL'),('CLIP','CLIP'),('VAE','VAE')])
    pos = node(2,'CLIPTextEncode',360,0,['text'],[result['positive']],[('CONDITIONING','CONDITIONING')])
    neg = node(3,'CLIPTextEncode',360,220,['text'],[result['negative']],[('CONDITIONING','CONDITIONING')])
    latent = node(4,'EmptyLatentImage',360,440,['width','height','batch_size'],[width,height,1],[('LATENT','LATENT')])
    sampler = node(5,'KSampler',720,0,['seed','control_after_generate','steps','cfg','sampler_name','scheduler','denoise'],
                   [seed,'fixed',28,7,'euler_ancestral','normal',1],[('LATENT','LATENT')])
    decode = node(6,'VAEDecode',1080,0,[],[],[('IMAGE','IMAGE')])
    preview = node(7,'PreviewImage',1440,0,[],[],[])
    def link(source, slot, target, name, typ):
        number = len(links)+1
        target_slot = len(target['inputs'])
        links.append([number,source['id'],slot,target['id'],target_slot,typ])
        source['outputs'][slot]['links'].append(number)
        target['inputs'].append({'name':name,'type':typ,'link':number})
    link(loader,1,pos,'clip','CLIP'); link(loader,1,neg,'clip','CLIP')
    link(loader,0,sampler,'model','MODEL'); link(pos,0,sampler,'positive','CONDITIONING')
    link(neg,0,sampler,'negative','CONDITIONING'); link(latent,0,sampler,'latent_image','LATENT')
    link(sampler,0,decode,'samples','LATENT'); link(loader,2,decode,'vae','VAE')
    link(decode,0,preview,'images','IMAGE')
    return {'last_node_id':7,'last_link_id':len(links),'nodes':nodes,'links':links,
            'groups':[],'config':{},'extra':{},'version':0.4}


