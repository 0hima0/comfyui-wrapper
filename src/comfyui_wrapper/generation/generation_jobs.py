"""Single and sequential generation workers, without HTTP request handling."""
from comfyui_wrapper.analysis import wd_tagger
import copy
import io
import threading
import time
import uuid
from datetime import datetime, timezone
from PIL import Image
from comfyui_wrapper.analysis import generate
from comfyui_wrapper.infrastructure import job_control, artifact_files
from comfyui_wrapper.workflows import person_workflow
from comfyui_wrapper.prompts import person_prompts
from comfyui_wrapper.analysis import analysis_reuse
from comfyui_wrapper.integrations import comfy_client
from comfyui_wrapper.generation.reference_images import close_references
from comfyui_wrapper.generation.generation_pipeline import analyze_references, build_workflow, analysis_report
from comfyui_wrapper.app_metadata import BASE
from comfyui_wrapper.generation import job_archive
class GenerationJobs:
    """Own worker state and execution; each application gets its own instance."""
    def __init__(self, runtime, history, storage, logger):
        self.runtime, self.history, self.storage, self.logger = runtime, history, storage, logger
        self.records, self.controls, self.batch_controls = {}, {}, {}
        self.lock, self.busy = threading.Lock(), threading.Lock()
        self.accept_lock = threading.Lock()
        self.batches = None
        self._progress_saved = {}

    def submit(self, references, settings, raw_seed, batch_plan=None, **reuse):
        from comfyui_wrapper.generation.submission import submit
        with self.accept_lock:
            return submit(self, references, settings, raw_seed, batch_plan, **reuse)

    def submission_receipt(self, request_id):
        if not request_id:return None
        job=self.history.get(request_id)
        if job and job.get('request_id')==request_id:return dict(job_id=request_id)
        batch=self.batches.get(request_id) if self.batches else None
        if batch and batch.get('request_id')==request_id:return dict(batch_id=request_id)
        return None

    def reconcile(self, job_id, import_images=False):
        from comfyui_wrapper.generation.job_recovery import reconcile
        return reconcile(self, job_id, import_images)

    def cancel(self, job_id):
        with self.lock:
            record = self.records.get(job_id)
            if record is not None and record.get('state') == 'running' and job_id in self.controls:
                self.controls[job_id].event.set()
                record.update(cancel_requested=True, message='停止処理中…（処理の終了を待っています）')
                self.history.save(job_id, record)
                return True
        if record is None and self.history.get(job_id) is None:
            raise KeyError(job_id)
        return False

    def active_batch(self):
        with self.lock:
            return next(iter(self.batch_controls), None)

    def cancel_batch(self, batch_id):
        with self.lock:
            if self.batches.get(batch_id) is None:
                raise KeyError(batch_id)
            control = self.batch_controls.get(batch_id)
            if control:
                control.event.set()
            return bool(control)

    def update(self, job_id, **values):
        with self.lock:
            if self.records[job_id].get('cancel_requested') and 'state' not in values:
                values['message'] = '停止処理中…（処理の終了を待っています）'
            self.records[job_id].update(values)
            self.history.save(job_id, self.records[job_id])

    def report_progress(self, job_id, stage, detail, current=None, total=None):
        progress = dict(stage=stage, detail=detail)
        if current is not None and total is not None:
            progress.update(current=current, total=total)
        with self.lock:
            record = self.records[job_id]
            record.update(progress=progress, message='停止処理中…（処理の終了を待っています）' if record.get('cancel_requested') else detail)
            now = time.monotonic()
            saved_at, saved_stage = self._progress_saved.get(job_id, (0, None))
            if stage != saved_stage or now - saved_at >= 1:
                self.history.save_progress(job_id, progress)
                self._progress_saved[job_id] = (now, stage)

    def get_job(self, job_id):
        with self.lock:
            record = copy.deepcopy(self.records.get(job_id))
        if record is None:
            record = self.history.get(job_id)
        if record and record.get('images') and (not record.get('output_files')):
            try:
                report = generate.read_json(self.runtime.root / job_id / 'analysis.json')
                record['output_files'] = [{'webui_filename': name, 'comfy_filename': descriptor.get('filename', ''), 'comfy_subfolder': descriptor.get('subfolder', ''), 'comfy_type': descriptor.get('type', 'output')} for name, descriptor in zip(record['images'], report.get('comfy_outputs', []))]
            except (OSError, ValueError, TypeError):
                pass
        return record

    def rebuild_archive(self, job_id):
        if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            raise KeyError(job_id)
        directory = self.runtime.root / job_id
        with self.lock:
            record = self.history.get(job_id)
            if record is None:
                raise KeyError(job_id)
            if job_id in self.records or record.get('state') == 'running' or record.get('temporary'):
                raise ValueError('実行中・選別前の成果物は再作成できません。')
            if not record.get('artifacts_ready') or directory.is_symlink() or directory.resolve().parent != self.runtime.root or not directory.is_dir():
                raise ValueError('保存済みの成果物が見つかりません。')
            # Reserve this execution while doing file I/O outside the shared lock.
            self.records[job_id] = dict(record, zip_building=True)
        try:
            result = job_archive.create(directory, self.logger)
            with self.lock:
                record = self.history.get(job_id)
                record.update(result)
                self.history.save(job_id, record)
            self.storage.invalidate()
            return result
        finally:
            with self.lock:
                self.records.pop(job_id, None)

    def run_job(self, job_id, references, settings, batch_cache=None, reused_analysis=None):
        job_control.local.control = self.controls[job_id]
        directory = self.runtime.root / job_id
        terminal = dict(state='error', message='処理が中断されました。')
        try:
            job_control.check()
            cache_key = settings['threshold']
            analysis = copy.deepcopy(reused_analysis) if reused_analysis is not None else copy.deepcopy(batch_cache.get(cache_key)) if batch_cache is not None else None
            if analysis is None:
                analysis = analyze_references(references, settings, self.runtime.wd_dir, self.runtime.ollama_url, lambda message, stage: (job_control.check(), self.report_progress(job_id, stage, message)))
                if batch_cache is not None:
                    batch_cache[cache_key] = copy.deepcopy(analysis)
            if batch_cache is not None or reused_analysis is not None:
                analysis['lora_assignments'] = settings['lora_assignments']
                for person in analysis.get('people', []):
                    person['loras'] = [v for v in settings['lora_assignments'] if v['reference_id'] == person['reference_id']]
            job_control.check()
            analysis.update(reuse_version=analysis_reuse.VERSION, reuse_fingerprint=analysis_reuse.fingerprint(references, settings))
            if reused_analysis is not None:
                self.report_progress(job_id, 'compose', '保存済みの解析結果を再利用しています。画像解析を省略します。')
            if reused_analysis is not None:
                analysis['result'], analysis['rating'] = generate.apply_rating(analysis['result'], settings['rating'], settings['target'], analysis.get('wd_predictions', []))
                if settings.get('preserve_people'):
                    analysis['result'] = person_prompts.enforce_count(analysis['result'], len(references), analysis['people'])
            result = analysis['result']
            if settings.get('preserve_people'):
                directory.mkdir(parents=True, exist_ok=False)
                people = copy.deepcopy(analysis['people'])
                subfolder = 'llmpc-' + job_id
                for person, reference in zip(people, references):
                    self.report_progress(job_id, 'compose', f'画像{reference.id}の人物参照を準備しています…')
                    name = f'reference_{reference.id}.png'
                    raw = person_workflow.reference_png(reference.image)
                    (directory / name).write_bytes(raw)
                    person['comfy_image'] = person_workflow.upload(self.runtime.comfy_url, raw, subfolder, name) if settings['execute'] else subfolder + '/' + name
                    person['saved_filename'] = name
                settings['person_references'] = people
            self.report_progress(job_id, 'compose', 'ワークフローを作成しています…')
            workflow = build_workflow(result, settings, BASE / 'workflows' / 'anima_template.json')
            sampler = next((n for n in workflow['nodes'] if n['type'] == 'KSampler'))
            self.update(job_id, generation_settings={k: v for k, v in sampler['widgets_values_named'].items() if k != 'control_after_generate'})
            directory.mkdir(parents=True, exist_ok=bool(settings.get('preserve_people')))
            generate.write_json(directory / 'workflow.json', workflow)
            report = analysis_report(analysis, settings)
            generate.write_json(directory / 'analysis.json', report)
            for key in ('positive', 'negative'):
                (directory / (key + '.txt')).write_text(result[key], encoding='utf-8')
            self.update(job_id, result=result, artifacts_ready=True, prompt_conflicts=report['prompt_conflicts'])
            if settings['execute']:
                graph = comfy_client.to_api(workflow)
                generate.write_json(directory / 'workflow_api.json', graph)

                def submitted(prompt_id):
                    report['prompt_id'] = prompt_id
                    generate.write_json(directory / 'analysis.json', report)
                    self.update(job_id, prompt_id=prompt_id)
                descriptors = comfy_client.execute(self.runtime.comfy_url, graph, workflow, submitted, lambda message: self.report_progress(job_id, 'queue', message), on_progress=lambda progress: self.report_progress(job_id, **progress), metadata={'schema': 'llmpc.image.v1', 'analysis': copy.deepcopy(report)})
                self.report_progress(job_id, 'save', '生成画像と設定情報を保存しています…')
                images, saved_descriptors, output_files = [], [], []
                output_wd = {}
                for index, descriptor in enumerate(descriptors):
                    name = f'image_{index}.png'
                    job_control.check()
                    raw = comfy_client.fetch_image(self.runtime.comfy_url, descriptor)
                    job_control.check()
                    wd_result = {'enabled': settings['use_wd'], 'source': 'generated_image', 'threshold': report['wd_threshold'], 'model': report['wd_model'], 'status': 'disabled', 'tags': '', 'predictions': []}
                    with Image.open(io.BytesIO(raw), formats=("PNG", "JPEG", "WEBP")) as generated:
                        if settings['use_wd']:
                            self.report_progress(job_id, 'save', '生成画像のWDタグを解析し、PNGに記録しています…')
                            try:
                                tags_out, predictions_out = wd_tagger.wd_tags(generated, self.runtime.wd_dir, settings['threshold'])
                                wd_result.update(status='done', tags=tags_out, predictions=predictions_out)
                            except Exception:
                                self.logger.exception('Generated image tagging failed: %s', name)
                                wd_result.update(status='error', error='生成画像のWD再解析に失敗しました。起動端末を確認してください。')
                        job_control.check()
                        metadata = {'schema': 'llmpc.image.v1', 'analysis': copy.deepcopy(report), 'generated_image_wd': wd_result, 'comfy_output': descriptor}
                        artifact_files.write_bytes(directory / name,
                            comfy_client.encode_png(generated, metadata, workflow, graph))
                    output_wd[name] = wd_result
                    images.append(name)
                    saved_descriptors.append(descriptor)
                    output_files.append(dict(webui_filename=name, comfy_filename=descriptor.get('filename', ''),
                                             comfy_subfolder=descriptor.get('subfolder', ''), comfy_type=descriptor.get('type', 'output')))
                    report.update(comfy_outputs=saved_descriptors, generated_images_wd=output_wd, output_files=output_files)
                    generate.write_json(directory / 'analysis.json', report)
                    self.update(job_id, images=list(images), output_files=copy.deepcopy(output_files))
            job_control.check()
            terminal = dict(state='done', message='画像生成が完了しました。' if settings['execute'] else 'プロンプトとワークフローを作成しました。')
        except job_control.JobCancelled as error:
            terminal = dict(state='cancelled', message=str(error))
        except generate.AnalysisError as error:
            self.logger.exception('Ollama analysis failed: %s', job_id)
            terminal = dict(state='error', message=str(error))
        except comfy_client.ComfyError as error:
            self.logger.exception('ComfyUI execution failed: %s', job_id)
            terminal = dict(state='error', message=str(error))
        except Exception:
            self.logger.exception('Image analysis failed: %s', job_id)
            terminal = dict(state='error', message='処理に失敗しました。起動端末のエラーを確認してください。Ollamaの起動・モデル名、WDのモデルファイルを確認して再実行してください。')
        finally:
            try:
                if directory.exists():
                    if terminal['state'] == 'done':
                        self.update(job_id, message='成果物をZIPにまとめています…', progress=dict(stage='save', detail='成果物をZIPにまとめています…'))
                    terminal.update(job_archive.create(directory, self.logger))
                terminal['finished_at'] = datetime.now(timezone.utc).isoformat()
                if terminal['state'] == 'done':
                    terminal['progress'] = dict(stage='done', detail=terminal['message'])
                with self.lock:
                    if self.controls[job_id].event.is_set() and terminal['state'] == 'done':
                        terminal.update(state='cancelled', message='ユーザーの操作で停止しました。')
                        terminal.pop('progress', None)
                    self.records[job_id].update(terminal)
                    self.history.save(job_id, self.records[job_id])
                    self.records.pop(job_id, None)
                self.storage.invalidate()
            finally:
                with self.lock:
                    self.controls.pop(job_id, None)
                    self._progress_saved.pop(job_id, None)
                job_control.local.control = None
                try:
                    if batch_cache is None:
                        close_references(references)
                finally:
                    if batch_cache is None:
                        self.busy.release()

    def run_batch(self, batch_id, references, planned, snapshot):
        control = self.batch_controls[batch_id]
        cache = {}
        try:
            for index, current in enumerate(planned):
                if control.event.is_set():
                    break
                job_id = uuid.uuid4().hex
                current['batch_sequence'] = dict(batch_id=batch_id, index=index + 1, count=len(planned))
                current['lora_assignments'] = person_prompts.assignments(current['loras'], [ref.id for ref in references], current['preserve_people'])
                with self.lock:
                    batch = self.batches.get(batch_id)
                    batch.update(current_job=job_id, current=index + 1, message=f'{index + 1} / {len(planned)} 回目を生成中です。')
                    batch['job_ids'].append(job_id)
                    self.batches.save(batch_id, batch)
                    self.controls[job_id] = control
                    record_settings = copy.deepcopy(snapshot)
                    record_settings.update(copy.deepcopy(current))
                    self.records[job_id] = dict(state='running', message=batch['message'], created_at=datetime.now(timezone.utc).isoformat(), settings=record_settings, batch_id=batch_id, temporary=True, batch_index=index + 1, progress=dict(stage='upload', detail=batch['message']))
                    self.history.save(job_id, self.records[job_id])
                self.run_job(job_id, references, current, cache)
                with self.lock:
                    record = self.history.get(job_id)
                    batch = self.batches.get(batch_id)
                    if record['state'] == 'done':
                        batch['completed'] += 1
                    self.batches.save(batch_id, batch)
                if record['state'] != 'done':
                    break
            with self.lock:
                batch = self.batches.get(batch_id)
                interrupted = control.event.is_set()
                state = 'cancelled' if interrupted else 'review' if batch['completed'] == len(planned) else 'error'
                detail = '連続生成を停止しました。' if interrupted else '連続生成が完了しました。' if state == 'review' else '連続生成を中断しました。' + (self.history.get(batch['current_job']) or {}).get('message', '')
                batch.update(state=state, message=detail + '残す画像を選び、選別を確定してください。', finished_at=datetime.now(timezone.utc).isoformat())
                self.batches.save(batch_id, batch)
        except Exception:
            self.logger.exception('Batch generation failed: %s', batch_id)
            with self.lock:
                batch = self.batches.get(batch_id)
                batch.update(state='error', finished_at=datetime.now(timezone.utc).isoformat(), message='連続生成が中断しました。完成済み画像を選別できます。')
                self.batches.save(batch_id, batch)
                current_id = batch.get('current_job')
                if current_id in self.records and self.records[current_id]['state'] == 'running':
                    self.records[current_id].update(state='error', message=batch['message'], finished_at=datetime.now(timezone.utc).isoformat())
                    self.history.save(current_id, self.records[current_id])
                    self.records.pop(current_id, None)
                    self._progress_saved.pop(current_id, None)
                    self.controls.pop(current_id, None)
        finally:
            close_references(references)
            with self.lock:
                self.batch_controls.pop(batch_id, None)
            self.busy.release()
