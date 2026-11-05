"""Persistent LoRA metadata, keyed by the full ComfyUI filename."""
from comfyui_wrapper.infrastructure.database import connection, migrate
from pathlib import Path
import json

def validate_tags(tags):
    if not isinstance(tags,list) or len(tags)>20 or any(not isinstance(tag,str) or not tag.strip() or len(tag.strip())>40 or any(ord(c)<32 for c in tag) for tag in tags):
        raise ValueError('管理用タグは各40文字・20個以内で指定してください。')
    result=[];seen=set()
    for tag in tags:
        tag=tag.strip()
        if tag.casefold() not in seen:result.append(tag);seen.add(tag.casefold())
    return result


class LoraStore:
    def __init__(self, path):
        self.path = Path(path)
        migrate(self.path, 'loras')

    def connect(self):
        return connection(self.path)

    def all(self):
        with self.connect() as db:
            return {row[0]:dict(trigger=row[1],url=row[2],note=row[3],tags=json.loads(row[4]),recommended_prompt=row[5])
                    for row in db.execute('SELECT name,trigger,url,note,tags,recommended_prompt FROM loras ORDER BY name')}

    def summaries(self):
        with self.connect() as db:
            return {name:dict(tags=json.loads(tags)) for name,tags in db.execute('SELECT name,tags FROM loras ORDER BY name')}

    def get(self,name):
        with self.connect() as db:
            row=db.execute('SELECT trigger,url,note,tags,recommended_prompt FROM loras WHERE name=?',(name,)).fetchone()
        return dict(trigger=row[0],url=row[1],note=row[2],tags=json.loads(row[3]),recommended_prompt=row[4]) if row else None

    def save(self, name, trigger, url, note, tags=None, recommended_prompt=None):
        checked=validate_tags(tags) if tags is not None else []
        with self.connect() as db:
            db.execute('INSERT INTO loras(name,trigger,url,note,tags,recommended_prompt) VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET '
                       'trigger=excluded.trigger,url=excluded.url,note=excluded.note,tags=CASE WHEN ? THEN loras.tags ELSE excluded.tags END,'
                       'recommended_prompt=CASE WHEN ? THEN loras.recommended_prompt ELSE excluded.recommended_prompt END',
                       (name,trigger,url,note,json.dumps(checked,ensure_ascii=False),recommended_prompt or '',tags is None,recommended_prompt is None))

    def delete(self, name):
        with self.connect() as db:
            db.execute('DELETE FROM loras WHERE name=?', (name,))

    def sample_names(self):
        with self.connect() as db:
            return [row[0] for row in db.execute('SELECT DISTINCT name FROM lora_samples ORDER BY name')]

    def samples(self,name):
        with self.connect() as db:
            rows=db.execute('SELECT id,name,filename,extension,mimetype,width,height FROM lora_samples WHERE name=? ORDER BY rowid',(name,)).fetchall()
        return [dict(zip(('id','name','filename','extension','mimetype','width','height'),row)) for row in rows]

    def sample(self,sample_id):
        with self.connect() as db:
            row=db.execute('SELECT id,name,filename,extension,mimetype,width,height FROM lora_samples WHERE id=?',(sample_id,)).fetchone()
        return dict(zip(('id','name','filename','extension','mimetype','width','height'),row)) if row else None

    def add_samples(self,name,rows):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count=db.execute('SELECT COUNT(*) FROM lora_samples WHERE name=?',(name,)).fetchone()[0]
            if count+len(rows)>6:raise ValueError('サンプル画像はLoRAごとに最大6枚です。')
            db.executemany('INSERT INTO lora_samples VALUES(?,?,?,?,?,?,?)',
                [(row['id'],name,row['filename'],row['extension'],row['mimetype'],row['width'],row['height']) for row in rows])

    def delete_sample(self,sample_id):
        with self.connect() as db:db.execute('DELETE FROM lora_samples WHERE id=?',(sample_id,))
