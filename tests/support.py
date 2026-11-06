"""Shared test fixtures; all images and upstream results are synthetic."""
from comfyui_wrapper.workflows import builders
import io
import time
import tempfile
from pathlib import Path
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def synthetic_anima_template():
    """Independent contract fixture built from our own generic test graph, no upstream JSON."""
    workflow = builders.animagine_workflow({'positive':'test scene','negative':'test negative'},512,512,1,'synthetic.safetensors')
    ids = {1:44, 2:11, 3:12, 4:28, 5:19, 6:8, 7:9}
    for node in workflow['nodes']:
        node['id'] = ids[node['id']]
    loader = next(n for n in workflow['nodes'] if n['id']==44)
    loader['type'] = 'UNETLoader'
    loader['outputs'] = loader['outputs'][:1]
    builders.set_widgets(loader,['unet_name','weight_dtype'],['synthetic-anima.safetensors','default'])
    for ident,kind,fields,values,output in (
        (45,'CLIPLoader',['clip_name','type','device'],['synthetic-clip.safetensors','stable_diffusion','default'],'CLIP'),
        (15,'VAELoader',['vae_name'],['synthetic-vae.safetensors'],'VAE')):
        item={'id':ident,'type':kind,'inputs':[],'outputs':[{'name':output,'type':output,'links':[]}],'mode':0}
        builders.set_widgets(item,fields,values)
        workflow['nodes'].append(item)
    for link in workflow['links']:
        old_source = link[1]
        link[1],link[3] = ids[old_source],ids[link[3]]
        if old_source==1 and link[2] in (1,2):
            link[1],link[2] = (45 if link[2]==1 else 15),0
    for node in workflow['nodes']:
        for output in node['outputs']:
            output['links']=[]
    by_id={n['id']:n for n in workflow['nodes']}
    for number,source,slot,*_ in workflow['links']:
        by_id[source]['outputs'][slot]['links'].append(number)
    workflow['last_node_id']=45
    return workflow

def image_upload(color='blue',size=(32,48),filename='reference.png',mode='RGB'):
    data=io.BytesIO()
    with Image.new(mode,size,color) as image:image.save(data,'PNG')
    data.seek(0)
    return data,filename

def wait_for_completion(client,url,app,timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        response=client.get(url)
        if response.status_code!=200:raise AssertionError(f'{url}: {response.status_code}')
        data=response.json
        if data['state']!='running' and not app.extensions['generation_lock'].locked():return data
        time.sleep(.01)
    raise AssertionError('Worker did not finish before test timeout: '+url)


class GalleryFixture:
    """Reusable gallery setup with no test cases of its own."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT_ROOT/'tests')
        self.root=Path(self.temp.name)
        from comfyui_wrapper.webui import create_app
        from comfyui_wrapper.gallery.history_store import HistoryStore
        self.client=create_app(self.root).test_client()
        self.store=HistoryStore(self.root/'history.sqlite3')

    def tearDown(self):
        self.temp.cleanup()

    def save(self,index,images=None,**extra):
        job=f'{index:032x}'
        record=dict(created_at=f'2026-10-21T00:{index:02d}:00+00:00',state='done',artifacts_ready=True,
                    images=images if images is not None else ['image_0.png'],
                    settings=dict(checkpoint='model.safetensors',seed=index,target='animagine',width=1024,height=1024,
                                  instruction='公園で二人',input_images=[dict(id=1,filename='person.png',role='人物')],
                                  loras=[dict(name='sdxl/person.safetensors',trigger='person',scope='image:1',strength_model=.7,strength_clip=.6)]),
                    result=dict(summary_ja='保存した画像'),generation_settings=dict(steps=28,cfg=5))
        record.update(extra)
        self.store.save(job,record)
        directory=self.root/job;directory.mkdir(exist_ok=True)
        for name in record['images']:
            if '/' not in name and '\\' not in name:Image.new('RGB',(8,8),'blue').save(directory/name)
        return job



def comfy_graph():
    from comfyui_wrapper.integrations import comfy_client
    from comfyui_wrapper.analysis import generate
    workflow=comfy_client.prepare(builders.animagine_workflow(
        {'positive':'blue dress','negative':'blurry'},768,1024,1,'model.safetensors'))
    return workflow,comfy_client.to_api(workflow)

def comfy_schema(graph):
    return {node['class_type']:{'input':{'required':{name:['ANY'] for name in node['inputs']}}}
            for node in graph.values()}
