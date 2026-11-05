"""Named settings only: no uploaded images, outputs or machine configuration."""
import json
import math
import sqlite3
import uuid
from pathlib import Path
from comfyui_wrapper.infrastructure.database import connection, migrate
from datetime import datetime, timezone
from comfyui_wrapper.workflows import sdxl_options

BOOLEAN_FIELDS={'execute','use_wd','preserve_people','use_quality_tags'}
TEXT_LIMITS={'target':20,'checkpoint':300,'profile':40,'instruction':8000,
             'additional_positive':8000,'additional_negative':8000,'rating':20,
             'seed':30,'sampler_name':100,'scheduler':100}
NUMBERS={'width':(256,2048),'height':(256,2048),'steps':(1,10000),'cfg':(0,100),
         'denoise':(0,1),'clip_skip':(0,24),'threshold':(0,1)}
FIELDS=BOOLEAN_FIELDS|TEXT_LIMITS.keys()|NUMBERS.keys()

def validate(data):
    if not isinstance(data,dict):raise ValueError('プリセットの形式が不正です。')
    name=data.get('name','')
    if not isinstance(name,str) or not 1<=len(name.strip())<=80 or '\x00' in name:raise ValueError('名前を1〜80文字で入力してください。')
    fields=data.get('fields')
    if not isinstance(fields,dict) or fields.keys()-FIELDS:raise ValueError('保存できない設定が含まれています。')
    for key,value in fields.items():
        if key in BOOLEAN_FIELDS:
            if type(value) is not bool:raise ValueError('チェック項目の値が不正です。')
        elif key in TEXT_LIMITS:
            if not isinstance(value,str) or len(value)>TEXT_LIMITS[key] or '\x00' in value:raise ValueError('設定の文字列が不正です。')
        else:
            if type(value) not in (str,int,float):raise ValueError('設定の数値が不正です。')
            try:number=float(value)
            except ValueError:raise ValueError('設定の数値が不正です。')
            low,high=NUMBERS[key]
            if not math.isfinite(number) or not low<=number<=high:raise ValueError('設定の数値が範囲外です。')
            if key in ('width','height','steps','clip_skip') and not number.is_integer():raise ValueError('整数で指定してください。')
            if key in ('width','height') and number%64:raise ValueError('幅・高さは64の倍数で指定してください。')
    if fields.get('target') not in ('anima','animagine') or not fields.get('checkpoint'):raise ValueError('生成モデルを選択してください。')
    if fields.get('profile','auto') not in {'auto',*sdxl_options.PROFILES}:raise ValueError('プロファイルが不正です。')
    if fields.get('rating','none') not in ('none','auto','safe','sensitive','nsfw','explicit'):raise ValueError('レーティングが不正です。')
    seed=fields.get('seed','').strip()
    if seed and (not seed.isdecimal() or not 0<=int(seed)<=2**53-1):raise ValueError('シードが不正です。')
    loras=sdxl_options.validate_loras(data.get('loras',[]))
    return dict(name=name.strip(),fields=fields,loras=loras)

class PresetStore:
    def __init__(self,path):
        self.path=Path(path)
        migrate(self.path, 'presets')

    def connect(self):
        return connection(self.path)

    def all(self):
        with self.connect() as db:rows=db.execute('SELECT id,payload,updated_at FROM presets ORDER BY updated_at DESC,id').fetchall()
        return [dict(id=row[0],**json.loads(row[1]),updated_at=row[2]) for row in rows]
    def save(self,data,preset_id=None):
        data=validate(data)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if preset_id is not None and db.execute('SELECT 1 FROM presets WHERE id=?',(preset_id,)).fetchone() is None:raise KeyError(preset_id)
            if preset_id is None and db.execute('SELECT COUNT(*) FROM presets').fetchone()[0]>=50:raise ValueError('プリセットは最大50件です。')
            preset_id=preset_id or uuid.uuid4().hex
            try:
                db.execute('INSERT INTO presets VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,payload=excluded.payload,updated_at=excluded.updated_at',
                    (preset_id,data['name'],json.dumps(data,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
            except sqlite3.IntegrityError:raise ValueError('同じ名前のプリセットがあります。別の名前にするか、対象を選んで更新してください。')
        return preset_id
    def delete(self,preset_id):
        with self.connect() as db:
            if db.execute('DELETE FROM presets WHERE id=?',(preset_id,)).rowcount==0:raise KeyError(preset_id)
