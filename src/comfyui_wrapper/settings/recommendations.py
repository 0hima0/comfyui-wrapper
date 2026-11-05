"""Validated, opt-in recommendations, scoped to exact model filenames."""
import json
import math

class RecommendationStore:
    def __init__(self,history):self.history=history

    def get(self,kind,name):
        self.validate_key(kind,name)
        with self.history.connect() as db:
            row=db.execute('SELECT payload FROM recommendations WHERE kind=? AND name=?',(kind,name)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def validate_key(kind,name):
        if kind not in ('model','lora') or not isinstance(name,str) or not name.strip() or len(name)>1024 or '\x00' in name:
            raise ValueError('モデルまたはLoRAの名前が不正です。')

    def save(self,kind,name,values):
        self.validate_key(kind,name)
        fields=({'steps':(1,10000),'cfg':(0,100),'clip_skip':(0,24)} if kind=='model' else
                {'strength_model':(-2,2),'strength_clip':(-2,2)})
        allowed=set(fields)|({'sampler_name','scheduler','negative'} if kind=='model' else set())
        if not isinstance(values,dict) or set(values)!=allowed:raise ValueError('推奨設定の項目が不正です。')
        for key,(lo,hi) in fields.items():
            value=values[key]
            if type(value) not in (int,float) or not lo<=value<=hi or not math.isfinite(value):
                raise ValueError('推奨設定の数値が範囲外です。')
            if key in ('steps','clip_skip') and value!=int(value):raise ValueError('StepsとCLIP skipは整数です。')
        for key in allowed-set(fields):
            limit=8000 if key=='negative' else 100
            if not isinstance(values[key],str) or len(values[key])>limit or '\x00' in values[key] or (key!='negative' and not values[key]):
                raise ValueError('推奨設定の文字列が不正です。')
        with self.history.connect() as db:
            db.execute('INSERT INTO recommendations VALUES(?,?,?) ON CONFLICT(kind,name) DO UPDATE SET payload=excluded.payload',
                       (kind,name,json.dumps(values,ensure_ascii=False)))
        return values

    def delete(self,kind,name):
        self.validate_key(kind,name)
        with self.history.connect() as db:db.execute('DELETE FROM recommendations WHERE kind=? AND name=?',(kind,name))
