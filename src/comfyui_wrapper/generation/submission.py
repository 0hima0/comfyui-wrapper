"""Own admission, worker startup and reference ownership independently of HTTP."""
import copy
import threading
import uuid
from datetime import datetime, timezone

from comfyui_wrapper.analysis import analysis_reuse, generate
from comfyui_wrapper.generation.batch_generation import variants
from comfyui_wrapper.generation.reference_images import close_references
from comfyui_wrapper.infrastructure import job_control
from comfyui_wrapper.prompts import person_prompts


class GenerationBusy(ValueError):
    pass


def submit(runner, references, settings, raw_seed, batch_plan=None, *,
           reuse_id='', final_positive=None, final_negative=None, request_id=None):
    """Take ownership of references; a worker or this function always closes them."""
    receipt=runner.submission_receipt(request_id)
    if receipt:
        close_references(references)
        return receipt
    if not runner.busy.acquire(blocking=False):
        close_references(references)
        raise GenerationBusy('別の画像を処理中です。完了後にもう一度実行してください。')
    identifier = None
    batch = None
    try:
        runtime = runner.runtime
        settings['lora_assignments'] = person_prompts.assignments(
            settings['loras'], [ref.id for ref in references], settings['preserve_people'])
        settings['input_images'] = [ref.describe() for ref in references]
        reused = None
        if reuse_id:
            if batch_plan is not None:
                raise ValueError('解析の再利用と連続生成は同時に実行できません。')
            if len(reuse_id) != 32 or any(c not in '0123456789abcdef' for c in reuse_id):
                raise ValueError('解析元の指定が不正です。')
            # Copy the report while deletion/finalization is excluded.
            with runner.lock:
                source = runner.history.get(reuse_id)
                if not source or not source.get('artifacts_ready') or source.get('state') == 'running':
                    raise ValueError('保存済みの解析元がありません。再解析してください。')
                report = generate.read_json(runtime.root / reuse_id / 'analysis.json')
            reused = analysis_reuse.restore(report, analysis_reuse.fingerprint(references, settings),
                                            final_positive, final_negative, reuse_id)
            settings['reused_from'] = reuse_id
        created_at = datetime.now(timezone.utc).isoformat()
        snapshot = copy.deepcopy(settings)
        snapshot['seed_input'] = raw_seed
        snapshot['input_image'] = ({key: settings['input_images'][0][key]
                                    for key in ('filename', 'width', 'height')} if references else None)
        snapshot['runtime'] = dict(ollama_url=runtime.ollama_url, comfy_url=runtime.comfy_url,
                                   wd_dir=str(runtime.wd_dir) if runtime.wd_dir else None,
                                   ollama_urls=runtime.ollama_urls, ollama_keep_alive=runtime.ollama_keep_alive)
        candidate = request_id or uuid.uuid4().hex
        if runner.history.get(candidate) or runner.batches.get(candidate):
            raise ValueError('受付IDが既存の実行と重複しています。')
        identifier = candidate
        if batch_plan is not None:
            planned = variants(batch_plan, settings)
            batch = dict(request_id=request_id,state='running', created_at=created_at, completed=0, current=0,
                         count=len(planned), job_ids=[], plan=batch_plan,
                         message='連続生成を開始しています。', checkpoint=settings.get('checkpoint', ''))
            runner.batches.save(identifier, batch)
            with runner.lock:
                runner.batch_controls[identifier] = job_control.JobControl()
            worker = threading.Thread(target=runner.run_batch,
                                      args=(identifier, references, planned, snapshot), daemon=True)
            reply = dict(batch_id=identifier)
        else:
            with runner.lock:
                runner.controls[identifier] = job_control.JobControl()
                runner.records[identifier] = dict(request_id=request_id,state='running', created_at=created_at,
                    message='生成リクエストを受け取りました。', settings=snapshot,
                    progress=dict(stage='upload', detail='生成リクエストを受け取りました。'))
                runner.history.save(identifier, runner.records[identifier])
            worker = threading.Thread(target=runner.run_job,
                args=(identifier, references, settings, None, reused), daemon=True)
            reply = dict(job_id=identifier)
        worker.start()
        return reply
    except Exception:
        try:
            if identifier is not None:
                with runner.lock:
                    runner.controls.pop(identifier, None)
                    runner.batch_controls.pop(identifier, None)
                    record = runner.records.pop(identifier, None)
                finished = datetime.now(timezone.utc).isoformat()
                if batch is not None:
                    batch.update(state='error', finished_at=finished, message='連続生成を開始できませんでした。')
                    runner.batches.save(identifier, batch)
                elif record is not None:
                    record.update(state='error', finished_at=finished, message='処理を開始できませんでした。')
                    runner.history.save(identifier, record)
        finally:
            try:
                close_references(references)
            finally:
                runner.busy.release()
        raise
