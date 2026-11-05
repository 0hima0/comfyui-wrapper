"""Delete completed executions with a database-level favorite guard."""
import json
import logging
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone


class DeleteBlocked(ValueError):
    pass


class ExecutionCleanup:
    def __init__(self, history, root, lock, jobs, thumbnails=None, *, retention_days=10):
        self.history, self.root, self.lock, self.jobs = history, root, lock, jobs
        self.thumbnails=thumbnails
        self.retention_days=retention_days
        self.stop = threading.Event()
        self.worker = None

    def delete(self, job_id, expired_before=None):
        if not re.fullmatch('[0-9a-f]{32}',job_id):raise KeyError(job_id)
        directory=self.root/job_id
        staging=self.root/'.deleting'
        pending=staging/job_id
        moved=False
        cached=[]
        with self.lock:
            if any(self.jobs.get(job_id,{}).get(key) for key in ('zip_building','artifact_busy')):
                raise DeleteBlocked('成果物を処理しています。完了後に削除してください。')
            with self.history.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT record FROM executions WHERE id=?',(job_id,)).fetchone()
                if row is None:raise KeyError(job_id)
                record=json.loads(row[0])
                if record.get('temporary'):raise DeleteBlocked('連続生成レビューの「選別を確定」から削除してください。')
                if record.get('state')=='running' or not record.get('artifacts_ready') or not record.get('images'):
                    raise DeleteBlocked('完了した生成画像のある実行だけ削除できます。')
                if db.execute('SELECT 1 FROM image_favorites WHERE job_id=? LIMIT 1',(job_id,)).fetchone():
                    raise DeleteBlocked('お気に入りを含む実行は削除できません。')
                if expired_before is not None and not self.expired(record,expired_before):
                    return False
                if directory.is_symlink() or directory.resolve().parent!=self.root:
                    raise DeleteBlocked('保存先が不正なため削除できません。')
                if staging.is_symlink() or staging.resolve().parent!=self.root:
                    raise DeleteBlocked('削除用の保存先が不正です。')
                try:
                    if self.thumbnails:
                        for name in record['images']:
                            if not isinstance(name,str) or '/' in name or '\\' in name:continue
                            try:cached.append(self.thumbnails.path_for(directory/name))
                            except OSError:pass
                    if directory.exists():
                        staging.mkdir(exist_ok=True)
                        directory.rename(pending)
                        moved=True
                    db.execute('DELETE FROM image_favorites WHERE job_id=?',(job_id,))
                    db.execute('DELETE FROM executions WHERE id=?',(job_id,))
                    db.commit()
                except Exception:
                    if moved:pending.rename(directory)
                    raise
            self.jobs.pop(job_id,None)
        if moved:self.purge(pending)
        for path in cached:
            try:path.unlink(missing_ok=True)
            except OSError:logging.getLogger(__name__).warning('Could not remove cached thumbnail: %s',path.name)
        return True

    @staticmethod
    def expired(record, cutoff):
        try:
            value=datetime.fromisoformat(record.get('finished_at') or record['created_at'])
            if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
            return value<=cutoff
        except (ValueError,TypeError,KeyError):
            return False

    def purge(self, pending):
        try:
            staging=self.root/'.deleting'
            if (pending.parent!=staging or staging.is_symlink() or staging.resolve().parent!=self.root
                    or pending.resolve().parent!=staging.resolve()):
                logging.getLogger(__name__).error('Refused unexpected deletion path: %s',pending)
                return
            if pending.is_dir() and not pending.is_symlink():shutil.rmtree(pending)
        except OSError:
            logging.getLogger(__name__).exception('Deleted execution files will be removed on the next cleanup: %s',pending.name)

    def sweep(self, now=None):
        cutoff=(now or datetime.now(timezone.utc))-timedelta(days=self.retention_days)
        ids=[]
        if self.retention_days:
            with self.history.connect() as db:
                ids=[row[0] for row in db.execute(
                    "SELECT id FROM executions WHERE json_extract(record,'$.state')!='running' "
                    "AND json_extract(record,'$.artifacts_ready')=1 AND json_array_length(record,'$.images')>0 "
                    "AND COALESCE(json_extract(record,'$.temporary'),0)=0 "
                    "AND NOT EXISTS (SELECT 1 FROM image_favorites WHERE job_id=executions.id) "
                    "AND julianday(COALESCE(NULLIF(json_extract(record,'$.finished_at'),''),json_extract(record,'$.created_at'))) <= julianday(?)",(cutoff.isoformat(),))]
        deleted=0
        for job_id in ids:
            try:deleted+=bool(self.delete(job_id,expired_before=cutoff))
            except (KeyError,DeleteBlocked):pass
            except OSError:logging.getLogger(__name__).exception('Execution cleanup failed: %s',job_id)
        staging=self.root/'.deleting'
        if staging.is_dir() and not staging.is_symlink():
            for path in staging.iterdir():
                # A database record means a previously interrupted transaction may need recovery.
                if re.fullmatch('[0-9a-f]{32}',path.name):
                    with self.lock:
                        if self.history.get(path.name) is None:self.purge(path)
                        elif not (self.root/path.name).exists():path.rename(self.root/path.name)
        return deleted

    def start(self):
        if self.worker is not None:return
        def run():
            while not self.stop.is_set():
                try:self.sweep()
                except Exception:logging.getLogger(__name__).exception('Automatic gallery cleanup failed')
                self.stop.wait(3600)
        self.worker=threading.Thread(target=run,name='gallery-cleanup',daemon=True)
        self.worker.start()
