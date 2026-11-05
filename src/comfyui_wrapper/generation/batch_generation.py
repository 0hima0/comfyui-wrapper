"""Bounded sequential plans and durable review galleries."""
import copy
import json
import math
import re
import shutil
import zipfile
import logging
import threading
from itertools import product
from datetime import datetime, timezone
from comfyui_wrapper.gallery.gallery_thumbnails import ThumbnailCache


def variants(raw,settings):
    if not isinstance(raw,dict) or type(raw.get('count')) is not int or not 1<=raw['count']<=20:
        raise ValueError('連続生成は1〜20回で指定してください。')
    mode=raw.get('mode','linear')
    if mode not in ('linear','matrix'):raise ValueError('連続生成の方式が不正です。')
    if not settings['execute']:raise ValueError('連続生成では「ComfyUIで画像も生成する」をオンにしてください。')
    ranges=raw.get('ranges')
    if not isinstance(ranges,list) or not 1<=len(ranges)<=9:raise ValueError('変更する数値を選んでください。')
    keys=set()
    for item in ranges:
        if not isinstance(item,dict):raise ValueError('連続生成の設定が不正です。')
        field=item.get('field');index=item.get('lora')
        if field=='threshold':
            if not settings['use_wd']:raise ValueError('しきい値を変える場合はWD Taggerをオンにしてください。')
            lo,hi=0,1;key=(field,None)
        elif field in ('cfg','steps'):
            lo,hi=(0,100) if field=='cfg' else (1,10000);key=(field,None)
        elif field in ('strength_model','strength_clip'):
            if type(index) is not int or not 0<=index<len(settings['loras']):raise ValueError('変更対象のLoRAを指定してください。')
            lo,hi=-2,2;key=(field,index)
        else:raise ValueError('連続生成の変更対象が不正です。')
        if key in keys:raise ValueError('変更対象が重複しています。')
        keys.add(key)
        for name in ('start','end'):
            value=item.get(name)
            if type(value) not in (int,float) or not lo<=value<=hi or not math.isfinite(value):
                raise ValueError('連続生成の開始値・終了値が範囲外です。')
    if mode=='matrix':
        if len(ranges)>2:raise ValueError('条件マトリクスは最大2軸です。')
        counts=[item.get('points') for item in ranges]
        if any(type(n) is not int or not 2<=n<=20 for n in counts) or math.prod(counts)>20:
            raise ValueError('各軸は2点以上、合計20枚以内にしてください。')
        if raw['count']!=math.prod(counts):raise ValueError('生成回数とマトリクスの組み合わせ数が一致しません。')
        axes=[]
        for item,count in zip(ranges,counts):
            values=[round(item['start']+(item['end']-item['start'])*i/(count-1),6) for i in range(count)]
            if item['field']=='steps':values=[round(v) for v in values]
            if len(set(values))!=len(values):raise ValueError('同じ値が重複する軸があります。範囲または点数を調整してください。')
            axes.append(values)
        planned=[]
        for row,column in product(range(counts[1] if len(counts)>1 else 1),range(counts[0])):
            current=copy.deepcopy(settings);values=[axes[0][column]]+([axes[1][row]] if len(axes)>1 else [])
            for item,value in zip(ranges,values):
                if item['field'] in ('cfg','steps'):current['generation_effective'][item['field']]=value
                elif item['field']=='threshold':current['threshold']=value
                else:current['loras'][item['lora']][item['field']]=value
            current['batch_cell']=dict(row=row,column=column,columns=counts[0],values=[dict(field=item['field'],lora=item.get('lora'),value=value) for item,value in zip(ranges,values)])
            planned.append(current)
        return planned
    result=[]
    for i in range(raw['count']):
        current=copy.deepcopy(settings)
        for item in ranges:
            value=round(item['start']+(item['end']-item['start'])*i/max(1,raw['count']-1),6)
            if item['field'] in ('cfg','steps'):current['generation_effective'][item['field']]=round(value) if item['field']=='steps' else value
            elif item['field']=='threshold':current['threshold']=value
            else:current['loras'][item['lora']][item['field']]=value
        result.append(current)
    return result


class BatchStore:
    def __init__(self,history,root,lock,jobs):
        self.history,self.root,self.lock,self.jobs=history,root,lock,jobs
        self.finalize_lock = threading.Lock()
        self.recover()
        with history.connect() as db:
            for batch_id,raw in db.execute('SELECT id,record FROM batches').fetchall():
                value=json.loads(raw)
                if value['state']=='running':
                    value.update(state='interrupted',finished_at=datetime.now(timezone.utc).isoformat(),message='再起動により連続生成が中断しました。完成済み画像を選別してください。')
                    db.execute('UPDATE batches SET record=? WHERE id=?',(json.dumps(value,ensure_ascii=False),batch_id))

    def get(self,batch_id):
        with self.history.connect() as db:
            row=db.execute('SELECT record FROM batches WHERE id=?',(batch_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self,batch_id,value):
        with self.history.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT record FROM batches WHERE id=?',(batch_id,)).fetchone()
            if existing and 'name' in json.loads(existing[0]):
                value=dict(value,name=json.loads(existing[0])['name'])
            db.execute('INSERT INTO batches VALUES(?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record',
                       (batch_id,json.dumps(value,ensure_ascii=False)))

    def rename(self,batch_id,name):
        if not isinstance(name,str) or len(name.strip())>80:
            raise ValueError('生成セット名は80文字以内で入力してください。')
        with self.lock, self.history.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT record FROM batches WHERE id=?',(batch_id,)).fetchone()
            if row is None:raise KeyError(batch_id)
            value=json.loads(row[0]);value['name']=name.strip()
            db.execute('UPDATE batches SET record=? WHERE id=?',(json.dumps(value,ensure_ascii=False),batch_id))
        return value['name']

    def all(self):
        with self.history.connect() as db:rows=db.execute('SELECT id,record FROM batches ORDER BY rowid DESC').fetchall()
        return [dict(batch_id=k,**json.loads(v)) for k,v in rows]

    def remove_tree(self,path):
        base=self.root/'.batch-finalize'
        if base.is_symlink() or base.resolve().parent!=self.root or path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
            raise ValueError('連続生成レビューの保存先が不正です。')
        if path.is_dir():shutil.rmtree(path)

    def recover(self):
        base=self.root/'.batch-finalize'
        if not base.exists():return
        if base.is_symlink() or base.resolve().parent!=self.root:raise ValueError('一時保存先が不正です。')
        for directory in base.iterdir():
            if not re.fullmatch('[a-f0-9]{32}',directory.name) or directory.is_symlink():continue
            originals=directory/'originals'
            if self.get(directory.name) is not None and originals.is_dir():
                for original in originals.iterdir():
                    if not re.fullmatch('[a-f0-9]{32}',original.name):continue
                    destination=self.root/original.name
                    if destination.exists():
                        # The replacement is inside the reviewed execution folder.
                        replacement=directory/('rollback-'+original.name)
                        destination.rename(replacement)
                    original.rename(destination)
            self.remove_tree(directory)

    def _review_records(self, db, batch_id):
        return dict(db.execute(
            "SELECT id,record FROM executions WHERE json_extract(record,'$.batch_id')=? "
            "AND json_extract(record,'$.temporary')=1", (batch_id,)))

    @staticmethod
    def _validate_selection(db, raw_records, selected):
        records = {key: json.loads(value) for key, value in raw_records.items()}
        allowed = {key + '/' + name for key, record in records.items()
                   for name in record.get('images', []) if isinstance(name, str)}
        if set(selected) - allowed:
            raise ValueError('選択した画像が連続生成レビューにありません。')
        favorites = {key + '/' + name for key, name in db.execute(
            'SELECT job_id,filename FROM image_favorites') if key in records}
        if favorites - set(selected):
            raise ValueError('お気に入りの画像は削除できません。')
        if any(not re.fullmatch('[a-f0-9]{32}', key) for key in records):
            raise ValueError('実行IDが不正です。')
        return records

    def _prepare_review(self, stage, records, selected):
        """Copy/repack outside the generation lock and SQLite write transaction."""
        kept, cached = {}, []
        thumbnails = ThumbnailCache(self.root / '.gallery-thumbnails')
        for job, original in records.items():
            record = copy.deepcopy(original)
            source = self.root / job
            if source.is_symlink() or source.resolve().parent != self.root:
                raise ValueError('画像の保存先が不正です。')
            names = [name for name in record.get('images', []) if job + '/' + name in selected]
            for name in record.get('images', []):
                if name not in names and isinstance(name, str) and '/' not in name and '\\' not in name:
                    try:
                        cached.append(thumbnails.path_for(source / name))
                    except OSError:
                        pass
            if not names:
                continue
            if any('/' in name or '\\' in name or not (source / name).is_file() for name in names):
                raise ValueError('残す画像ファイルが見つかりません。')
            target = stage / 'ready' / job
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('results.zip'))
            original_names = list(record['images'])
            for name in original_names:
                if name not in names and '/' not in name and '\\' not in name:
                    (target / name).unlink(missing_ok=True)
            record.update(images=names, temporary=False)
            record['output_files'] = [value for value in record.get('output_files', [])
                                      if value['webui_filename'] in names]
            report_path = target / 'analysis.json'
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding='utf-8'))
                report['output_files'] = record['output_files']
                report['generated_images_wd'] = {key: value for key, value in
                    report.get('generated_images_wd', {}).items() if key in names}
                if 'comfy_outputs' in report:
                    report['comfy_outputs'] = [value for name, value in
                        zip(original_names, report['comfy_outputs']) if name in names]
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            with zipfile.ZipFile(target / 'results.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in target.iterdir():
                    if path.is_file() and path.name != 'results.zip':
                        archive.write(path, path.name)
            kept[job] = record
        return kept, cached

    def _rollback_review(self, stage):
        for original in (stage / 'originals').iterdir():
            destination = self.root / original.name
            if destination.exists():
                destination.rename(stage / ('rollback-' + original.name))
            original.rename(destination)

    def finalize(self, batch_id, selected):
        """Prepare without shared locks; revalidate and switch atomically at commit."""
        if not re.fullmatch('[a-f0-9]{32}', batch_id):
            raise KeyError(batch_id)
        if not isinstance(selected, list) or any(not isinstance(key, str) for key in selected) or len(selected) > 400:
            raise ValueError('残す画像の指定が不正です。')
        selected = list(dict.fromkeys(selected))
        if not self.finalize_lock.acquire(blocking=False):
            raise ValueError('別の選別を確定しています。完了後に再実行してください。')
        stage = self.root / '.batch-finalize' / batch_id
        owns_stage = False
        try:
            with self.history.connect() as db:
                batch = self.get(batch_id)
                if batch is None:
                    raise KeyError(batch_id)
                if batch['state'] == 'running':
                    raise ValueError('連続生成を停止するか、完了を待ってください。')
                snapshot = self._review_records(db, batch_id)
                records = self._validate_selection(db, snapshot, selected)
            if stage.exists():
                raise ValueError('前回の確定処理が残っています。サービスを再起動してください。')
            if stage.parent.is_symlink() or stage.parent.resolve().parent != self.root:
                raise ValueError('保存先が不正です。')
            (stage / 'originals').mkdir(parents=True)
            owns_stage = True
            kept, cached = self._prepare_review(stage, records, selected)
            # Only renames and DB updates run while generation/cancellation is excluded.
            with self.lock:
                with self.history.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    try:
                        current_batch = self.get(batch_id)
                        if current_batch != batch or self._review_records(db, batch_id) != snapshot:
                            raise ValueError('レビュー内容が変更されました。再読み込みしてください。')
                        self._validate_selection(db, snapshot, selected)
                        for job in records:
                            source = self.root / job
                            if source.is_symlink() or source.resolve().parent != self.root:
                                raise ValueError('画像の保存先が不正です。')
                            if source.exists():
                                source.rename(stage / 'originals' / job)
                            if job in kept:
                                (stage / 'ready' / job).rename(source)
                        for job in records:
                            if job in kept:
                                db.execute('UPDATE executions SET record=? WHERE id=?',
                                    (json.dumps(kept[job], ensure_ascii=False), job))
                            else:
                                db.execute('DELETE FROM executions WHERE id=?', (job,))
                        db.execute('DELETE FROM batches WHERE id=?', (batch_id,))
                        db.commit()
                    except Exception:
                        db.rollback()
                        self._rollback_review(stage)
                        raise
                for job in records:
                    self.jobs.pop(job, None)
            # Database commit is the recovery marker; no originals should be restored now.
            owns_stage = False
            try:
                self.remove_tree(stage)
            except OSError:
                logging.getLogger(__name__).exception('Temporary files will be removed on restart')
            for path in cached:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logging.getLogger(__name__).warning('Could not remove temporary thumbnail: %s', path.name)
            return len(selected)
        finally:
            try:
                if owns_stage:
                    # A failed rollback must be left for recover(), not deleted.
                    if not any((stage / 'originals').iterdir()):
                        self.remove_tree(stage)
            finally:
                self.finalize_lock.release()
