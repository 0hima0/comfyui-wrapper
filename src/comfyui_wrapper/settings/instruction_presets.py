"""Named instruction text, independent of model and generation settings."""
import sqlite3
import uuid
from datetime import datetime,timezone
from pathlib import Path
from comfyui_wrapper.infrastructure.database import connection,migrate

class InstructionStore:
    def __init__(self,path):
        self.path=Path(path);migrate(self.path,'instructions')

    def all(self):
        with connection(self.path) as db:
            rows=db.execute('SELECT id,name,instruction FROM instructions ORDER BY name COLLATE NOCASE,id').fetchall()
        return [dict(id=key,name=name,instruction=text) for key,name,text in rows]

    def save(self,data,key=None):
        if not isinstance(data,dict):raise ValueError('入力形式が不正です。')
        name,text=data.get('name'),data.get('instruction')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80 or any(ord(c)<32 for c in name):raise ValueError('名前は1〜80文字で入力してください。')
        if not isinstance(text,str) or not text.strip() or len(text)>8000 or '\x00' in text:raise ValueError('指示は1〜8000文字で入力してください。')
        with connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if key is not None and not db.execute('SELECT 1 FROM instructions WHERE id=?',(key,)).fetchone():raise KeyError(key)
            if key is None and db.execute('SELECT COUNT(*) FROM instructions').fetchone()[0]>=100:raise ValueError('保存できる指示は最大100件です。')
            key=key or uuid.uuid4().hex
            try:db.execute('INSERT INTO instructions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,instruction=excluded.instruction,updated_at=excluded.updated_at',(key,name.strip(),text,datetime.now(timezone.utc).isoformat()))
            except sqlite3.IntegrityError:raise ValueError('同じ名前の指示があります。別の名前にするか、選択した指示を更新してください。')
        return key

    def delete(self,key):
        with connection(self.path) as db:
            if not db.execute('DELETE FROM instructions WHERE id=?',(key,)).rowcount:raise KeyError(key)
