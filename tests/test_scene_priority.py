from comfyui_wrapper.workflows import builders
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from werkzeug.datastructures import MultiDict
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.prompts import person_prompts
from comfyui_wrapper.workflows import person_workflow
from comfyui_wrapper.workflows import sdxl_options
from comfyui_wrapper.webui import create_app

INSTRUCTION='公園のベンチに画像1の人物と画像2の人物が並んで座る。\n2人は手を繋ぎ、顔を見合って笑いながら話している。\n俯瞰構図にする。\n文字は含めない。'
SCENE='two characters sitting side by side on a park bench, holding hands, looking at each other, smiling, talking, top-down view'


class ScenePriorityTests(unittest.TestCase):
    def test_scene_uses_only_instruction_without_images_or_source_background(self):
        result=dict(summary_ja='ベンチの二人',positive=SCENE,negative='text, watermark',uncertainties_ja='')
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(dict(done=True,message=dict(content=json.dumps(result)))).encode())) as call:
            self.assertEqual(generate.analyze(None,INSTRUCTION,'','http://ollama','model','animagine',
                             references=[dict(id=1),dict(id=2)],scene_only=True),result)
        payload=json.loads(call.call_args.args[0].data)
        self.assertNotIn('images',payload['messages'][1])
        self.assertEqual(json.loads(payload['messages'][1]['content'])['user_instruction'],INSTRUCTION)
        self.assertIn('gaze direction',payload['messages'][0]['content'])
        self.assertIn('Do not invent a white studio background',payload['messages'][0]['content'])

    def test_lora_binding_auto_explicit_global_and_invalid_target(self):
        rows=[dict(name='a',scope='auto'),dict(name='b',scope='image:7'),dict(name='style',scope='global')]
        bound=person_prompts.assignments(rows,[2,7],True)
        self.assertEqual([r['reference_id'] for r in bound],[2,7,None])
        self.assertEqual(person_prompts.global_loras(bound),[bound[2]])
        with_style=person_prompts.assignments([rows[2],dict(name='a'),dict(name='b')],[2,7],True)
        self.assertEqual([r['reference_id'] for r in with_style],[None,2,7])
        self.assertTrue(all(r['reference_id'] is None for r in person_prompts.assignments(rows,[2,7],False)))
        with self.assertRaises(ValueError):person_prompts.assignments([dict(name='a',scope='image:1')],[2,7],True)
        with self.assertRaises(ValueError):person_prompts.assignments([dict(name=str(i)) for i in range(3)],[2,7],True)
        with self.assertRaises(ValueError):sdxl_options.validate_loras([dict(name='a',scope='bad')])

    def test_person_hooks_are_distinct_and_not_applied_to_shared_model(self):
        base=builders.animagine_workflow(dict(positive='exactly two distinct people, '+SCENE,negative='text, solo, blurry'),1024,1024,1,'animagine.safetensors')
        people=[dict(reference_id=i+1,comfy_image=f'job/ref{i}.png',positive=f'1girl, outfit_{i}, trigger_{i}',
                     loras=[dict(name=f'character{i}.safetensors',strength_model=.7,strength_clip=.7)]) for i in range(2)]
        graph=comfy_client.to_api(person_workflow.extend(base,people,dict(adapter='adapter',vision='vision'),1024,1024))
        self.assertFalse(any(n['class_type']=='LoraLoader' for n in graph.values()))
        hooks={nid:n for nid,n in graph.items() if n['class_type']=='CreateHookLora'}
        self.assertEqual(len(hooks),2)
        for i in range(2):
            hook_id=next(nid for nid,node in hooks.items() if node['inputs']['lora_name']==f'character{i}.safetensors')
            hooked=next((nid,node) for nid,node in graph.items() if node['class_type']=='SetClipHooks' and node['inputs']['hooks'][0]==hook_id)
            self.assertTrue(hooked[1]['inputs']['apply_to_conds'])
            texts=[n['inputs']['text'] for n in graph.values() if n['class_type']=='CLIPTextEncode' and n['inputs']['clip'][0]==hooked[0]]
            self.assertEqual(len(texts),2)  # Hooked positive and negative must match the same person.
            positive=next(t for t in texts if f'trigger_{i}' in t)
            self.assertNotIn(f'trigger_{1-i}',positive)
            self.assertIn('holding hands',positive);self.assertIn('top-down view',positive)
            self.assertNotIn('two distinct people',positive)
            negative=next(t for t in texts if f'trigger_{i}' not in t)
            self.assertNotIn('solo',negative)
        sampler=next(n for n in graph.values() if n['class_type']=='KSampler')
        self.assertEqual(graph[sampler['inputs']['negative'][0]]['class_type'],'ConditioningCombine')
        self.assertEqual(sum(n['class_type']=='KSampler' for n in graph.values()),1)

    def test_count_is_explicit_and_source_solo_pose_removed(self):
        people=[dict(positive='1girl, red jacket'),dict(positive='1girl, blue dress')]
        result=person_prompts.enforce_count(dict(positive='solo, 1girl, garden',negative='blurry'),2,people)
        self.assertIn('exactly two distinct people',result['positive']);self.assertIn('2girls',result['positive'])
        self.assertNotIn('1girl',result['positive']);self.assertIn('single person',result['negative'])
        appearance=person_prompts.appearance('solo, 1girl, standing, looking at viewer, red jacket, blue eyes')
        self.assertEqual(appearance,'1girl, red jacket, blue eyes')

    def test_export_keeps_character_triggers_out_of_shared_prompt(self):
        def png(color):
            stream=io.BytesIO();Image.new('RGB',(8,8),color).save(stream,'PNG');stream.seek(0);return stream
        loras=[dict(name='sdxl/character_a.safetensors',strength_model=.7,strength_clip=.7,trigger='character_a_trigger'),
               dict(name='sdxl/character_b.safetensors',strength_model=.7,strength_clip=.7,trigger='character_b_trigger')]
        def analyze(image,instruction,tags,url,model,target,**kwargs):
            if kwargs.get('scene_only'):
                self.assertIsNone(image);self.assertEqual(kwargs['ui_positive'],'')
                positive=SCENE
            else:positive='solo, 1girl, standing, '+('red jacket' if image.getpixel((0,0))[:3]==(255,0,0) else 'blue dress')
            return dict(positive=positive,negative='text, blurry',summary_ja='二人',uncertainties_ja='')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
            client=create_app(Path(temp)).test_client()
            form=MultiDict([('image',(png('red'),'character_a.png')),('image',(png('blue'),'character_b.png')),
                           ('target','animagine'),('checkpoint','animagine-xl-4.0-opt.safetensors'),('preserve_people','on'),
                           ('instruction',INSTRUCTION),('loras',json.dumps(loras))])
            with patch('comfyui_wrapper.analysis.generate.analyze',side_effect=analyze):
                response=client.post('/api/jobs',data=form,headers={'X-Requested-With':'LLMPC'})
                self.assertEqual(response.status_code,202,response.json)
                job=response.json['job_id'];deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    record=client.get('/api/jobs/'+job).json
                    if record['state']!='running':break
                    time.sleep(.01)
                self.assertEqual(record['state'],'done',record)
            self.assertNotIn('character_a_trigger',record['result']['positive']);self.assertNotIn('character_b_trigger',record['result']['positive'])
            report=json.loads((Path(temp)/job/'analysis.json').read_text(encoding='utf-8'))
            self.assertIn('character_a_trigger',report['people'][0]['positive']);self.assertNotIn('character_b_trigger',report['people'][0]['positive'])
            self.assertIn('character_b_trigger',report['people'][1]['positive'])
            graph=comfy_client.to_api(json.loads((Path(temp)/job/'workflow.json').read_text(encoding='utf-8')))
            self.assertEqual(sum(n['class_type']=='CreateHookLora' for n in graph.values()),2)
            self.assertEqual([r['reference_id'] for r in record['settings']['lora_assignments']],[1,2])
