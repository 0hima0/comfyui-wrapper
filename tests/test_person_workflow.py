from comfyui_wrapper.workflows import builders
import copy
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from werkzeug.datastructures import MultiDict
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.workflows import person_workflow
from comfyui_wrapper.workflows import sdxl_options
from comfyui_wrapper.webui import create_app


class PersonWorkflowTests(unittest.TestCase):
    def people(self, count):
        return [dict(reference_id=i+1, comfy_image=f'job/ref_{i+1}.png', positive=f'outfit_{i+1}') for i in range(count)]

    def test_masks_assign_each_image_and_text_to_same_band_after_lora(self):
        base=builders.animagine_workflow(dict(positive='people in garden',negative='blurry'),1024,768,1,'WAI.safetensors')
        base=sdxl_options.extend_workflow(base,[dict(name='illustrious/face.safetensors',strength_model=.7,strength_clip=.6)],2)
        original=copy.deepcopy(base)
        for count in (2,3,4):
            with self.subTest(count=count):
                workflow=person_workflow.extend(base,self.people(count),dict(adapter='plus',vision='vision'),1024,768)
                graph=comfy_client.to_api(workflow)
                adapters=[(nid,n) for nid,n in graph.items() if n['class_type']=='IPAdapterAdvanced']
                bands=[]
                for index,(nid,adapter) in enumerate(adapters):
                    mask_id=adapter['inputs']['attn_mask'][0]
                    mask=graph[mask_id]['inputs']
                    feather=graph[mask['source'][0]]
                    self.assertEqual(feather['class_type'],'FeatherMask')
                    band=graph[feather['inputs']['mask'][0]]['inputs']
                    bands.append((mask['x'],band['width']))
                    self.assertEqual(band['height'],768)
                    self.assertEqual(graph[adapter['inputs']['image'][0]]['inputs']['image'],f'job/ref_{index+1}.png')
                    scoped=next(n for n in graph.values() if n['class_type']=='ConditioningSetMask' and n['inputs']['mask'][0]==mask_id)
                    self.assertEqual(scoped['inputs']['set_cond_area'],'default')
                    self.assertLess(adapter['inputs']['end_at'],1)
                    text=graph[scoped['inputs']['conditioning'][0]]
                    self.assertIn(f'outfit_{index+1}',text['inputs']['text'])
                    self.assertIn('garden',text['inputs']['text'])
                    self.assertEqual(graph[text['inputs']['clip'][0]]['class_type'],'CLIPSetLastLayer')
                    previous=graph[adapter['inputs']['model'][0]]['class_type']
                    self.assertEqual(previous,'LoraLoader' if index==0 else 'IPAdapterAdvanced')
                self.assertEqual(bands[0][0],0)
                self.assertEqual(sum(bands[-1]),1024)
                for (x,w),(next_x,_) in zip(bands,bands[1:]):
                    self.assertGreater(x+w,next_x)
                sampler=next(n for n in graph.values() if n['class_type']=='KSampler')
                self.assertEqual(sampler['inputs']['model'][0],adapters[-1][0])
                self.assertEqual(graph[sampler['inputs']['positive'][0]]['class_type'],'ConditioningCombine')
                self.assertEqual(sum(n['class_type']=='KSampler' for n in graph.values()),1)
                # Every UI link has matching source/output and target/input references.
                nodes={n['id']:n for n in workflow['nodes']}
                for number,src,slot,dst,dslot,typ in workflow['links']:
                    self.assertIn(number,nodes[src]['outputs'][slot]['links'])
                    self.assertEqual(nodes[dst]['inputs'][dslot]['link'],number)
                    self.assertEqual(nodes[src]['outputs'][slot]['type'],typ)
        self.assertEqual(base,original)

    def test_required_models_checked_and_selected_by_family(self):
        info={name:{} for name in person_workflow.REQUIRED}
        info['IPAdapterModelLoader']=dict(input=dict(required=dict(ipadapter_file=[[
            'sdxl/ip-adapter-plus_sdxl_vit-h.safetensors','ip-adapter-plus_sd15.safetensors']])))
        info['CLIPVisionLoader']=dict(input=dict(required=dict(clip_name=[[person_workflow.VISION]])))
        with patch('comfyui_wrapper.integrations.comfy_client.api',return_value=info):
            self.assertEqual(person_workflow.resolve_models('url','illustrious')['adapter'],'sdxl/ip-adapter-plus_sdxl_vit-h.safetensors')
            self.assertEqual(person_workflow.resolve_models('url','sd15')['adapter'],'ip-adapter-plus_sd15.safetensors')
        with self.assertRaisesRegex(ValueError,'未対応'):
            person_workflow.adapter_name('anima')
        with patch('comfyui_wrapper.integrations.comfy_client.api',return_value={}):
            with self.assertRaisesRegex(ValueError,'IPAdapterAdvanced'):
                person_workflow.resolve_models('url','sdxl')

        info['IPAdapterModelLoader']['input']['required']['ipadapter_file']=[[]]
        with patch('comfyui_wrapper.integrations.comfy_client.api',return_value=info):
            with self.assertRaisesRegex(ValueError,'ip-adapter-plus'):
                person_workflow.resolve_models('url','sdxl')

    def test_soft_regions_have_no_gaps_and_keep_person_centres_separate(self):
        for width in (256,1024,2048):
            for count in (2,3,4):
                base=builders.animagine_workflow(dict(positive='garden',negative='blurry'),width,768,1,'WAI.safetensors')
                graph=comfy_client.to_api(person_workflow.extend(base,self.people(count),dict(adapter='plus',vision='vision'),width,768))
                cache={}
                def mask_values(nid):
                    if nid in cache:return cache[nid]
                    node=graph[nid];p=node['inputs'];kind=node['class_type']
                    if kind=='SolidMask': values=[p['value']]*p['width']
                    elif kind=='FeatherMask':
                        values=mask_values(p['mask'][0]).copy()
                        for x in range(p['left']):values[x]*=(x+1)/p['left']
                        for x in range(p['right']):values[-x-1]*=(x+1)/p['right']
                    elif kind=='MaskComposite':
                        values=mask_values(p['destination'][0]).copy()
                        for x,value in enumerate(mask_values(p['source'][0])): values[p['x']+x]+=value
                    else:self.fail(kind)
                    cache[nid]=values;return values
                masks=[mask_values(n['inputs']['attn_mask'][0]) for n in graph.values() if n['class_type']=='IPAdapterAdvanced']
                for x in range(width):
                    self.assertGreaterEqual(sum(m[x] for m in masks),1-1e-6)
                    self.assertLessEqual(sum(m[x] for m in masks),1.07)
                for index,mask in enumerate(masks):
                    centre=width*(2*index+1)//(count*2)
                    self.assertEqual(mask[centre],1)
                    self.assertTrue(all(other[centre]==0 for i,other in enumerate(masks) if i!=index))
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(mask,mask[1:])),1/16+1e-6)

    def test_reference_is_padded_and_upload_path_verified(self):
        image=Image.new('RGBA',(100,300),'red')
        raw=person_workflow.reference_png(image)
        self.assertEqual(image.size,(100,300))
        with Image.open(io.BytesIO(raw)) as square:
            self.assertEqual(square.size,(1024,1024))
            self.assertEqual(square.getpixel((0,0)),(255,255,255))
            self.assertEqual(square.getpixel((512,512)),(255,0,0))
        response=dict(name='ref.png',subfolder='llmpc-test',type='input')
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as call:
            self.assertEqual(person_workflow.upload('http://comfy',raw,'llmpc-test','ref.png'),'llmpc-test/ref.png')
        self.assertIn(raw,call.call_args.args[0].data)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"name":"wrong"}')):
            with self.assertRaises(ValueError):person_workflow.upload('http://comfy',raw,'llmpc-test','ref.png')

    def test_web_export_preserves_distinct_prompts_images_and_history(self):
        def png(color):
            data=io.BytesIO();Image.new('RGB',(16,32),color).save(data,'PNG');data.seek(0);return data
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            client=create_app(Path(temp)).test_client()
            data=MultiDict([('image',(png('red'),'one.png')),('image',(png('blue'),'two.png')),
                            ('target','animagine'),('checkpoint','waiIllustriousSDXL_v170.safetensors'),
                            ('preserve_people','on'),('instruction','庭で並ぶ')])
            results=[dict(positive='two people, garden',negative='blurry',summary_ja='庭',uncertainties_ja=''),
                     dict(positive='red jacket, black trousers',negative='blurry',summary_ja='人物1',uncertainties_ja=''),
                     dict(positive='white blouse, blue skirt',negative='blurry',summary_ja='人物2',uncertainties_ja='')]
            seen=[]
            def analyze(*args, **kwargs):
                if args[0] is not None and not isinstance(args[0],list):seen.append(args[0].getpixel((0,0))[:3])
                return results[len(seen)] if seen else results[0]
            with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=analyze) as analysis:
                response=client.post('/api/jobs',data=data,headers={'X-Requested-With':'LLMPC'})
                self.assertEqual(response.status_code,202,response.json)
                job=response.json['job_id'];deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    record=client.get('/api/jobs/'+job).json
                    if record['state']!='running':break
                    time.sleep(.01)
                self.assertEqual(record['state'],'done',record)
                self.assertEqual(analysis.call_count,3)
                self.assertIn('Exclude all clothing',analysis.call_args_list[0].args[1])
                self.assertEqual(seen,[(255,0,0),(0,0,255)])
            report=json.loads((Path(temp)/job/'analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(report['reference_mode'],'regional_ipadapter')
            self.assertEqual(report['person_preservation']['blending']['version'],'scene_priority_v3')
            self.assertIn('shared background',report['result']['positive'])
            self.assertIn('split screen',report['result']['negative'])
            self.assertEqual([p['positive'] for p in report['people']],[r['positive'] for r in results[1:]])
            with zipfile.ZipFile(Path(temp)/job/'results.zip') as archive:
                self.assertIn('reference_1.png',archive.namelist());self.assertIn('reference_2.png',archive.namelist())
                graph=comfy_client.to_api(json.loads(archive.read('workflow.json')))
                self.assertEqual(sum(n['class_type']=='IPAdapterAdvanced' for n in graph.values()),2)
            restored=client.get('/api/history/'+job+'/restore').json
            self.assertTrue(restored['fields']['preserve_people'])

    def test_web_uploads_each_person_before_comfy_execution(self):
        def png(color):
            data=io.BytesIO();Image.new('RGB',(8,16),color).save(data,'PNG');data.seek(0);return data
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            client=create_app(Path(temp)).test_client()
            data=MultiDict([('image',(png('red'),'a.png')),('image',(png('blue'),'b.png')),
                           ('target','animagine'),('checkpoint','waiIllustriousSDXL_v170.safetensors'),
                           ('execute','on'),('preserve_people','on')])
            results=[dict(positive=text,negative='blurry',summary_ja='庭',uncertainties_ja='')
                     for text in ('two people, garden','red jacket','blue dress')]
            uploads=[]
            def upload(url,raw,folder,name):
                with Image.open(io.BytesIO(raw)) as image: uploads.append((name,image.getpixel((512,512))))
                return folder+'/'+name
            def execute(url,graph,workflow,submitted,status,**kwargs):
                self.assertEqual(uploads,[('reference_1.png',(255,0,0)),('reference_2.png',(0,0,255))])
                self.assertEqual(sum(n['class_type']=='IPAdapterAdvanced' for n in graph.values()),2)
                self.assertEqual(kwargs['metadata']['analysis']['reference_mode'],'regional_ipadapter')
                # Subfolder upload paths are not advertised in LoadImage's root-file dropdown.
                comfy_client.validate({k:n for k,n in graph.items() if n['class_type']=='LoadImage'},
                                      {'LoadImage':{'input':{'required':{'image':[['unrelated-root.png']]}}}})
                submitted('two-people')
                return [dict(filename='people.png',subfolder='',type='output')]
            info={'CheckpointLoaderSimple':{'input':{'required':{'ckpt_name':[['waiIllustriousSDXL_v170.safetensors']]}}}}
            with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=results),patch('comfyui_wrapper.workflows.person_workflow.resolve_models',return_value=dict(adapter='plus',vision='vision')), \
                 patch('comfyui_wrapper.workflows.person_workflow.upload',side_effect=upload),patch('comfyui_wrapper.integrations.comfy_client.execute',side_effect=execute), \
                 patch('comfyui_wrapper.integrations.comfy_client.fetch_image',return_value=png('green').getvalue()), \
                 patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(info).encode())):
                response=client.post('/api/jobs',data=data,headers={'X-Requested-With':'LLMPC'})
                self.assertEqual(response.status_code,202,response.json)
                job=response.json['job_id'];deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    record=client.get('/api/jobs/'+job).json
                    if record['state']!='running':break
                    time.sleep(.01)
                self.assertEqual(record['state'],'done',record)
                self.assertEqual(len(record['images']),1)
            with Image.open(Path(temp)/job/'image_0.png') as image:
                metadata=json.loads(image.text['llmpc'])['analysis']
            self.assertEqual(metadata['person_preservation']['references'][1]['positive'],'blue dress')

    def test_anima_preservation_rejected_before_analysis(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            client=create_app(Path(temp)).test_client()
            def png():
                data=io.BytesIO();Image.new('RGB',(8,8)).save(data,'PNG');data.seek(0);return data
            data=MultiDict([('image',(png(),'one.png')),('image',(png(),'two.png')),('preserve_people','on'),('checkpoint','synthetic-anima.safetensors')])
            with patch('comfyui_wrapper.analysis.generate.analyze') as analysis:
                response=client.post('/api/jobs',data=data,headers={'X-Requested-With':'LLMPC'})
            self.assertEqual(response.status_code,400)
            self.assertIn('Anima',response.json['error']);analysis.assert_not_called()
