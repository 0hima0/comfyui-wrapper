"""Transactional SQLite schema upgrades with backups of existing databases."""
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMAS = {
    'instructions': ((
        'CREATE TABLE instructions (id TEXT PRIMARY KEY,name TEXT UNIQUE COLLATE NOCASE NOT NULL,instruction TEXT NOT NULL,updated_at TEXT NOT NULL)',
    ),),
    'history': ((
        'CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, record TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS executions_created_at ON executions(created_at DESC)',
        'CREATE TABLE IF NOT EXISTS image_favorites (job_id TEXT NOT NULL, filename TEXT NOT NULL, PRIMARY KEY(job_id,filename))',
        'CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, record TEXT NOT NULL)',
    ), (
        'CREATE TABLE execution_progress (job_id TEXT PRIMARY KEY REFERENCES executions(id) ON DELETE CASCADE, payload TEXT NOT NULL)',
    ), (
        'CREATE TABLE image_annotations (job_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE, filename TEXT NOT NULL, note TEXT NOT NULL, labels TEXT NOT NULL, PRIMARY KEY(job_id,filename))',
        'CREATE TABLE recommendations (kind TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,name))',
    ), (
        "CREATE INDEX executions_running ON executions(id) WHERE json_extract(record,'$.state')='running'",
        "CREATE INDEX executions_finished ON executions(julianday(COALESCE(NULLIF(json_extract(record,'$.finished_at'),''),json_extract(record,'$.created_at'))))",
    )),
    'presets': ((
        'CREATE TABLE IF NOT EXISTS presets (id TEXT PRIMARY KEY,name TEXT UNIQUE COLLATE NOCASE, payload TEXT NOT NULL, updated_at TEXT NOT NULL)',
    ),),
    'loras': ((
        'CREATE TABLE IF NOT EXISTS loras (name TEXT PRIMARY KEY, trigger TEXT NOT NULL, url TEXT NOT NULL, note TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS lora_samples (id TEXT PRIMARY KEY,name TEXT NOT NULL,filename TEXT NOT NULL,extension TEXT NOT NULL,mimetype TEXT NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL)',
        'CREATE INDEX IF NOT EXISTS lora_samples_name ON lora_samples(name)',
    ), (
        "ALTER TABLE loras ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'",
    ), (
        "ALTER TABLE loras ADD COLUMN recommended_prompt TEXT NOT NULL DEFAULT ''",
    )),
}


@contextmanager
def connection(path, timeout=15):
    db = sqlite3.connect(path, timeout=timeout)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            yield db
    finally:
        db.close()


def migrate(path, schema):
    """Upgrade once under a write reservation; never downgrade newer databases."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    steps = SCHEMAS[schema]
    existed = path.is_file() and path.stat().st_size > 0
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > len(steps):
            raise ValueError(f'{path.name}: DBの版がアプリより新しいため起動できません。新しいアプリを使用してください。')
        if version == len(steps):
            return
        if existed:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = path.with_name(f'{path.stem}.pre-v{len(steps)}.{stamp}.{uuid.uuid4().hex[:8]}.sqlite3')
            # A separate reader sees the committed pre-upgrade state, including WAL data.
            with connection(path) as source, connection(backup) as destination:
                source.backup(destination)
        for index in range(version, len(steps)):
            for statement in steps[index]:
                db.execute(statement)
            db.execute(f'PRAGMA user_version = {index + 1}')
