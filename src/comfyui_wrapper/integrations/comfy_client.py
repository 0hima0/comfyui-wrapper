"""ComfyUI local API adapter for the two supported workflow families."""
import copy
import io
import json
import time
import uuid
from comfyui_wrapper.infrastructure import job_control
from comfyui_wrapper.integrations.comfy_progress import ComfyProgress
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image
from PIL.PngImagePlugin import PngInfo


class ComfyError(RuntimeError):
    pass


def api(url, route, payload=None, timeout=30):
    request = urllib.request.Request(url.rstrip('/') + route,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(16000).decode('utf-8', errors='replace')
        raise ComfyError('ComfyUIが実行を拒否しました: ' + detail[:3000]) from error
    except (OSError, ValueError) as error:
        raise ComfyError('ComfyUIに接続できません: ' + str(error)) from error


def prepare(workflow):
    workflow = copy.deepcopy(workflow)
    for node in workflow['nodes']:
        if node['type'] == 'PreviewImage':
            node['type'] = 'SaveImage'
            node['widgets_values'] = ['LLMPC']
            node['widgets_values_named'] = {'filename_prefix': 'LLMPC'}
            node['properties'] = {'Node name for S&R': 'SaveImage'}
    return workflow


def to_api(workflow):
    allowed = {'VAELoader','VAEDecode','CLIPLoader','SaveImage','PreviewImage','KSampler',
               'EmptyLatentImage','UNETLoader','CLIPTextEncode','CheckpointLoaderSimple','LoraLoader','CLIPSetLastLayer','LoadImage','SolidMask','FeatherMask','MaskComposite','CLIPVisionLoader',
               'IPAdapterModelLoader','IPAdapterAdvanced','ConditioningSetMask','ConditioningCombine','CreateHookLora','SetClipHooks'}
    links = {link[0]: link for link in workflow['links']}
    graph = {}
    for node in workflow['nodes']:
        kind = node['type']
        if kind not in allowed or node.get('mode',0) != 0:
            raise ComfyError('未対応のノードです: ' + kind)
        inputs = dict(node.get('widgets_values_named', {}))
        inputs.pop('control_after_generate', None)
        for field in node.get('inputs', []):
            if field.get('link') is not None:
                link = links[field['link']]
                inputs[field['name']] = [str(link[1]), link[2]]
        graph[str(node['id'])] = {'class_type':kind, 'inputs':inputs}
    return graph


def validate(graph, info):
    for node in graph.values():
        kind, inputs = node['class_type'], node['inputs']
        if kind not in info:
            raise ComfyError('ComfyUIに必要なノードがありません: ' + kind)
        schema = info[kind].get('input', {})
        for name, spec in schema.get('required', {}).items():
            if name not in inputs:
                raise ComfyError(f'必須設定がありません: {kind}.{name}')
        for name, value in inputs.items():
            spec = {**schema.get('required', {}), **schema.get('optional', {})}.get(name)
            if spec is None:
                raise ComfyError(f'ComfyUIと設定が一致しません: {kind}.{name}')
            if isinstance(value,list) and len(value)==2 and isinstance(value[1],int):
                continue
            # LoadImage validates uploaded subfolder paths itself; its dropdown lists only root files.
            if isinstance(spec[0], list) and value not in spec[0] and not (kind == 'LoadImage' and name == 'image'):
                raise ComfyError(f'ComfyUIで選択できない設定です: {kind}.{name} = {value}')


def execute(url, graph, workflow, on_submitted, on_status, timeout=1800, interval=2, metadata=None, on_progress=None):
    job_control.check()
    validate(graph, api(url, '/object_info'))
    extra = {'workflow': workflow}
    if metadata is not None:
        extra['llmpc'] = metadata
    client_id = uuid.uuid4().hex
    tracker = ComfyProgress(url, client_id, graph) if on_progress is not None else None
    try:
        job_control.check()
        reply = api(url, '/prompt', {'prompt': graph, 'client_id': client_id,
                    'extra_data': {'extra_pnginfo': extra}})
        if reply.get('node_errors') or not reply.get('prompt_id'):
            raise ComfyError('ComfyUIの実行検証に失敗しました: ' + json.dumps(reply,ensure_ascii=False)[:3000])
        prompt_id = str(reply['prompt_id'])
        if tracker is not None:
            tracker.bind(prompt_id)
        on_submitted(prompt_id)
        on_status('ComfyUIで画像を生成しています…（キュー待ちを含みます）')
        deadline = time.monotonic() + timeout
        cancel_sent = False
        control = job_control.current()
        while time.monotonic() < deadline:
            if control is not None and control.event.is_set():
                if not cancel_sent:
                    try:
                        api(url, '/api/jobs/' + urllib.parse.quote(prompt_id, safe='') + '/cancel', {})
                    except ComfyError as error:
                        raise ComfyError('ComfyUIへの停止要求に失敗しました。ComfyUI側でキュー・実行状況を確認してください。個別停止APIに対応するComfyUIへの更新が必要な場合があります。 ' + str(error)) from error
                    cancel_sent = True
                queue = api(url, '/queue')
                outstanding = queue.get('queue_running', []) + queue.get('queue_pending', [])
                if not any(str(row[1]) == prompt_id for row in outstanding):
                    raise job_control.JobCancelled('ユーザーの操作で停止しました。')
            if tracker is not None:
                progress = tracker.poll()
                if progress is not None:
                    on_progress(progress)
            record = api(url, '/history/' + urllib.parse.quote(prompt_id, safe='')).get(prompt_id)
            if record:
                if cancel_sent:
                    raise job_control.JobCancelled('ユーザーの操作で停止しました。')
                status = record.get('status', {})
                if status.get('status_str') == 'error':
                    raise ComfyError('ComfyUIで画像生成に失敗しました: ' + json.dumps(status.get('messages',[]),ensure_ascii=False)[:3000])
                if status.get('completed') or status.get('status_str') == 'success':
                    images = [image for output in record.get('outputs',{}).values() for image in output.get('images',[])]
                    if not images:
                        raise ComfyError('ComfyUIは完了しましたが、出力画像がありません。')
                    return images
            time.sleep(interval)
        raise ComfyError('画像生成の待機が30分を超えました。ComfyUIのキューと履歴を確認してください。自動再送はしません。')
    finally:
        if tracker is not None:
            tracker.close()


def encode_png(image, metadata=None, workflow=None, graph=None):
    """Preserve existing PNG text, including ComfyUI prompt/workflow."""
    info = PngInfo()
    text = dict(getattr(image, 'text', {}))
    if workflow is not None:
        text['workflow'] = json.dumps(workflow, ensure_ascii=False)
    if graph is not None:
        text['prompt'] = json.dumps(graph, ensure_ascii=False)
    if metadata is not None:
        text['llmpc'] = json.dumps(metadata, ensure_ascii=False)
    for key, value in text.items():
        if isinstance(value, str):
            info.add_itxt(key, value, zip=True)
    output = io.BytesIO()
    image.save(output, format='PNG', pnginfo=info)
    return output.getvalue()


def fetch_image(url, descriptor):
    query = urllib.parse.urlencode({key:descriptor.get(key,'') for key in ('filename','subfolder','type')})
    with urllib.request.urlopen(url.rstrip('/') + '/view?' + query, timeout=60) as response:
        data = response.read(32*1024*1024+1)
    if len(data) > 32*1024*1024:
        raise ComfyError('生成画像が32MBを超えています。ComfyUIから保存してください。')
    with Image.open(io.BytesIO(data), formats=("PNG", "JPEG", "WEBP")) as image:
        if image.width * image.height > 24_000_000:
            raise ComfyError('生成画像が2400万画素を超えています。')
        return encode_png(image)
