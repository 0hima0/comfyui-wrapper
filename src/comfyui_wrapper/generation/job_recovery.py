"""Reconcile saved ComfyUI prompts without ever submitting another prompt."""
import copy
import io
from datetime import datetime, timezone
from urllib.parse import quote

from PIL import Image
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.infrastructure import artifact_files
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.generation import job_archive


def upstream_state(url, prompt_id, graph):
    try:
        history = comfy_client.api(url, '/history/' + quote(prompt_id, safe=''), timeout=5)
        record = history.get(prompt_id)
        if record:
            # A history response must identify the exact prompt and expected graph.
            prompt = record.get('prompt')
            if not isinstance(prompt, list) or len(prompt) < 3 or str(prompt[1]) != prompt_id or prompt[2] != graph:
                return dict(state='mismatch', message='ComfyUI履歴の実行IDまたはワークフローが一致しません。取り込みません。')
            status = record.get('status', {})
            if status.get('status_str') == 'error':
                return dict(state='failed', message='ComfyUIで実行が失敗しています。')
            if status.get('completed') or status.get('status_str') == 'success':
                # Ignore outputs from nodes not belonging to this workflow.
                descriptors = [image for node, output in record.get('outputs', {}).items()
                               if node in graph and graph[node].get('class_type') in ('SaveImage', 'PreviewImage')
                               for image in output.get('images', [])]
                if not descriptors:
                    return dict(state='missing', message='ComfyUI履歴に完成画像がありません。')
                return dict(state='completed', message='完成画像を取り込めます。', descriptors=descriptors)
        queue = comfy_client.api(url, '/queue', timeout=5)
        outstanding = queue.get('queue_running', []) + queue.get('queue_pending', [])
        if any(isinstance(row, list) and len(row) > 1 and str(row[1]) == prompt_id for row in outstanding):
            return dict(state='running', message='ComfyUIで実行中またはキュー待ちです。再投入しません。')
        return dict(state='missing', message='ComfyUIの履歴・キューに実行がありません。履歴消去済みの可能性があります。')
    except (comfy_client.ComfyError, ValueError, TypeError, AttributeError):
        return dict(state='unavailable', message='ComfyUIの状態を確認できません。接続を確認して再試行してください。')


def reconcile(runner, job_id, import_images=False):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise KeyError(job_id)
    directory = runner.runtime.root / job_id
    review_reserved = False
    with runner.lock:
        record = runner.history.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if job_id in runner.records or record.get('state') == 'running':
            raise ValueError('Wrapperの処理が終了してから再確認してください。')
        if directory.is_symlink() or directory.resolve().parent != runner.runtime.root:
            raise ValueError('成果物の保存先が不正です。')
        if not record.get('prompt_id') or not record.get('artifacts_ready'):
            raise ValueError('照合に必要な実行ID・設定が保存されていません。')
        if record.get('temporary'):
            review_reserved = runner.batches.finalize_lock.acquire(blocking=False)
            if not review_reserved:
                raise ValueError('生成セットを選別中です。完了後に再確認してください。')
        runner.records[job_id] = dict(record, artifact_busy=True)
    try:
        for name in ('analysis.json', 'workflow.json', 'workflow_api.json'):
            if (directory / name).is_symlink():
                raise ValueError('照合用ファイルの保存先が不正です。')
        report = generate.read_json(directory / 'analysis.json')
        graph = generate.read_json(directory / 'workflow_api.json')
        workflow = generate.read_json(directory / 'workflow.json')
        if not all(isinstance(value,dict) for value in (report,graph,workflow)):
            raise ValueError('照合用ファイルの形式が不正です。')
        prompt_id = record['prompt_id']
        if report.get('prompt_id') != prompt_id:
            raise ValueError('保存済みの実行IDが一致しません。')
        # Use the endpoint saved for this execution, not a subsequently changed setting.
        url = record.get('settings', {}).get('runtime', {}).get('comfy_url') or runner.runtime.comfy_url
        outcome = upstream_state(url, prompt_id, graph)
        descriptors = outcome.pop('descriptors', [])
        if not import_images or outcome['state'] != 'completed':
            return outcome
        if not runner.busy.acquire(blocking=False):
            raise ValueError('別の生成処理が実行中です。完了後に取り込んでください。')
        try:
            images = list(record.get('images', []))
            outputs = copy.deepcopy(record.get('output_files', []))
            known = {(row.get('comfy_filename'), row.get('comfy_subfolder', ''), row.get('comfy_type', 'output')):row
                     for row in outputs}
            for descriptor in descriptors:
                if not isinstance(descriptor, dict) or not isinstance(descriptor.get('filename'), str):
                    raise ValueError('ComfyUIの出力情報が不正です。')
                key = (descriptor['filename'], descriptor.get('subfolder', ''), descriptor.get('type', 'output'))
                existing = known.get(key)
                if existing and (directory / existing['webui_filename']).is_file():
                    continue
                name = existing['webui_filename'] if existing else f'image_{len(images)}.png'
                if '/' in name or '\\' in name or (directory / name).is_symlink():
                    raise ValueError('画像の保存先が不正です。')
                raw = comfy_client.fetch_image(url, descriptor)
                with Image.open(io.BytesIO(raw)) as image:
                    metadata = dict(schema='llmpc.image.v1', analysis=copy.deepcopy(report), comfy_output=descriptor,
                                    recovery=dict(prompt_id=prompt_id, generated_image_wd='not_reanalyzed'))
                    artifact_files.write_bytes(directory / name, comfy_client.encode_png(image, metadata, workflow, graph))
                if not existing:
                    images.append(name)
                    output = dict(webui_filename=name, comfy_filename=key[0], comfy_subfolder=key[1], comfy_type=key[2])
                    outputs.append(output)
                    known[key] = output
                report.update(output_files=outputs, comfy_outputs=[dict(filename=row['comfy_filename'], subfolder=row['comfy_subfolder'], type=row['comfy_type']) for row in outputs])
                generate.write_json(directory / 'analysis.json', report)
                # Persist each completed image; retries skip these exact descriptors.
                with runner.lock:
                    current = runner.history.get(job_id)
                    current.update(images=list(images), output_files=copy.deepcopy(outputs))
                    runner.history.save(job_id, current)
                    runner.records[job_id].update(images=list(images), output_files=copy.deepcopy(outputs))
            archive_result=job_archive.create(directory, runner.logger)
            with runner.lock:
                current = runner.history.get(job_id)
                current.update(state='done', interrupted=False, recovered=True,
                               finished_at=current.get('finished_at') or datetime.now(timezone.utc).isoformat(),
                               message='ComfyUIの完成画像を取り込みました。', progress=dict(stage='done',detail='完成画像の取り込みが完了しました。'))
                current.update(archive_result)
                runner.history.save(job_id, current)
                if current.get('temporary') and current.get('batch_id'):
                    batch=runner.batches.get(current['batch_id'])
                    if batch:
                        batch['completed']=sum((runner.history.get(job) or {}).get('state')=='done' for job in batch['job_ids'])
                        if batch['completed']==batch['count']:
                            batch.update(state='review',message='完成画像を取り込みました。残す画像を選別してください。')
                        runner.batches.save(current['batch_id'],batch)
            return dict(state='imported', message='完成画像を取り込みました。', images=images)
        finally:
            runner.busy.release()
    finally:
        with runner.lock:
            runner.records.pop(job_id, None)
        if review_reserved:
            runner.batches.finalize_lock.release()
        runner.storage.invalidate()
