"""Persistent execution settings and status, with a latest-20 listing."""
import json
from comfyui_wrapper.infrastructure.database import connection, migrate
from datetime import datetime, timezone
from pathlib import Path


class HistoryStore:
    def __init__(self,path):
        self.path=Path(path)
        migrate(self.path, 'history')
        with self.connect() as db:
            for job_id,raw in db.execute("SELECT id,record FROM executions WHERE json_extract(record,'$.state')='running'").fetchall():
                record=json.loads(raw)
                if record.get('state')=='running':
                    record.update(state='error',interrupted=True,finished_at=datetime.now(timezone.utc).isoformat(),message='サーバー再起動により追跡が中断されました。再実行前にComfyUIのキュー・履歴を確認してください。')
                    db.execute('UPDATE executions SET record=? WHERE id=?',(json.dumps(record,ensure_ascii=False),job_id))

    def connect(self):
        return connection(self.path, timeout=10)

    def save(self,job_id,record):
        payload = {key: value for key, value in record.items() if key != 'progress'}
        with self.connect() as db:
            db.execute('INSERT INTO executions(id,created_at,record) VALUES(?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET record=excluded.record',
                       (job_id,record['created_at'],json.dumps(payload,ensure_ascii=False)))
            if 'progress' in record:
                self._save_progress(db, job_id, record['progress'])

    @staticmethod
    def _save_progress(db, job_id, progress):
        db.execute('INSERT INTO execution_progress VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload',
                   (job_id, json.dumps(progress, ensure_ascii=False)))

    def save_progress(self, job_id, progress):
        with self.connect() as db:
            self._save_progress(db, job_id, progress)

    @staticmethod
    def _decode(raw, progress):
        record = json.loads(raw)
        if progress is not None:
            record['progress'] = json.loads(progress)
        return record

    def get(self,job_id):
        with self.connect() as db:
            row=db.execute('SELECT e.record,p.payload FROM executions e LEFT JOIN execution_progress p ON p.job_id=e.id WHERE e.id=?',(job_id,)).fetchone()
        return self._decode(*row) if row else None

    def latest(self):
        with self.connect() as db:
            rows=db.execute("SELECT e.id,e.record,p.payload FROM executions e LEFT JOIN execution_progress p ON p.job_id=e.id WHERE COALESCE(json_extract(e.record,'$.temporary'),0)=0 ORDER BY e.created_at DESC,e.rowid DESC LIMIT 20").fetchall()
        return [dict(job_id=job_id,**self._decode(raw,progress)) for job_id,raw,progress in rows]

    def recoverable(self):
        with self.connect() as db:
            rows=db.execute("SELECT id,record FROM executions WHERE json_extract(record,'$.state') IN ('error','cancelled') "
                            "AND json_extract(record,'$.prompt_id') IS NOT NULL ORDER BY created_at DESC,rowid DESC LIMIT 20").fetchall()
        return [dict(job_id=job,**json.loads(raw)) for job,raw in rows]

    def set_favorite(self, job_id, filename, favorite):
        with self.connect() as db:
            if favorite:
                db.execute('INSERT OR IGNORE INTO image_favorites(job_id,filename) VALUES(?,?)',(job_id,filename))
            else:
                db.execute('DELETE FROM image_favorites WHERE job_id=? AND filename=?',(job_id,filename))

    def annotations(self,job_id):
        return self.annotations_many([job_id]).get(job_id,{})

    def annotations_many(self,job_ids):
        ids=list(dict.fromkeys(job_ids))
        if not ids:return {}
        with self.connect() as db:
            rows=db.execute('SELECT job_id,filename,note,labels FROM image_annotations WHERE job_id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
        result={}
        for job_id,name,note,labels in rows:
            result.setdefault(job_id,{})[name]=dict(note=note,labels=json.loads(labels))
        return result

    def annotate(self,job_id,filename,note,labels):
        with self.connect() as db:
            db.execute('INSERT INTO image_annotations VALUES(?,?,?,?) ON CONFLICT(job_id,filename) DO UPDATE SET note=excluded.note,labels=excluded.labels',
                       (job_id,filename,note,json.dumps(labels,ensure_ascii=False)))

    def image_page(self, offset=0, limit=24, favorites_only=False, batch_id=None, filters=None):
        """Read only card metadata; full prompts and workflow settings are fetched on demand."""
        filters=filters or {}
        clauses=[];params=[]
        for key,path in [('model','$.settings.checkpoint'),('lora','$.settings.loras')]:
            if filters.get(key):
                if key=='lora':
                    clauses.append("AND EXISTS (SELECT 1 FROM json_each(record,'$.settings.loras') l WHERE instr(lower(json_extract(l.value,'$.name')),lower(?))>0) ");params.append(filters[key])
                else:
                    clauses.append("AND instr(lower(COALESCE(json_extract(record,?),'')),lower(?))>0 ");params.extend([path,filters[key]])
        if filters.get('q'):
            clauses.append("AND (instr(lower(COALESCE(json_extract(record,'$.settings.instruction'),'') || ' ' || COALESCE(json_extract(record,'$.result.positive'),'') || ' ' || COALESCE(json_extract(record,'$.result.negative'),'')),lower(?))>0 OR EXISTS (SELECT 1 FROM image_annotations a WHERE a.job_id=executions.id AND instr(lower(a.note || ' ' || a.labels),lower(?))>0)) ")
            params.extend([filters['q'],filters['q']])
        if filters.get('label'):
            clauses.append("AND EXISTS (SELECT 1 FROM image_annotations a,json_each(a.labels) label WHERE a.job_id=executions.id AND label.value=?) ")
            params.append(filters['label'])
        for key,op in [('after','>='),('before','<')]:
            if filters.get(key):
                clauses.append('AND julianday(created_at) '+op+' julianday(?) ');params.append(filters[key])
        with self.connect() as db:
            rows=db.execute(
                "SELECT id,created_at,json_extract(record,'$.images'),json_extract(record,'$.output_files'), "
                "json_extract(record,'$.settings.checkpoint'),json_extract(record,'$.settings.width'), "
                "json_extract(record,'$.settings.height'),json_extract(record,'$.settings.seed'), "
                "json_extract(record,'$.result.summary_ja'),json_extract(record,'$.batch_index'), "
                "json_extract(record,'$.settings.threshold'),json_extract(record,'$.settings.loras'),json_extract(record,'$.settings.use_wd'),json_extract(record,'$.settings.batch_cell'), "
                "instr(lower(COALESCE(json_extract(record,'$.settings.instruction'),'') || ' ' || COALESCE(json_extract(record,'$.result.positive'),'') || ' ' || COALESCE(json_extract(record,'$.result.negative'),'')),lower(?))>0 FROM executions "
                "WHERE json_array_length(record,'$.images')>0 "
                "AND json_extract(record,'$.artifacts_ready')=1 "
                "AND json_extract(record,'$.state')!='running' "
                + ("AND json_extract(record,'$.temporary')=1 AND json_extract(record,'$.batch_id')=? " if batch_id else "AND COALESCE(json_extract(record,'$.temporary'),0)=0 ")
                + ("AND EXISTS (SELECT 1 FROM image_favorites f JOIN json_each(executions.record,'$.images') i "
                   "ON i.value=f.filename WHERE f.job_id=executions.id) " if favorites_only else '') +
                ''.join(clauses)+'ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?', [filters.get('q','')]+([batch_id] if batch_id else [])+params+[limit+1,offset]).fetchall()
            favorites={}
            if rows:
                ids=[row[0] for row in rows[:limit]]
                for job_id,name in db.execute('SELECT job_id,filename FROM image_favorites WHERE job_id IN ('+','.join('?' for _ in ids)+')',ids):
                    favorites.setdefault(job_id,[]).append(name)
        items=[]
        for job_id,created_at,images,outputs,checkpoint,width,height,seed,summary,batch_index,threshold,loras,use_wd,cell,text_match in rows[:limit]:
            items.append(dict(job_id=job_id,created_at=created_at,images=json.loads(images),favorites=favorites.get(job_id,[]),batch_index=batch_index,batch_cell=json.loads(cell) if cell else None,text_match=bool(text_match),
                output_files=json.loads(outputs) if outputs else [],
                settings=dict(checkpoint=checkpoint,width=width,height=height,seed=seed,threshold=threshold,loras=json.loads(loras) if loras else [],use_wd=bool(use_wd)),
                result=dict(summary_ja=summary)))
        return items,len(rows)>limit
