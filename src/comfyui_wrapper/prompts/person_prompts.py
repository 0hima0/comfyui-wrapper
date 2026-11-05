"""Separate shared scene instructions from person-specific appearance and LoRAs."""
import re


def assignments(loras, reference_ids, enabled):
    resolved=[]
    person_index=0
    for row in loras:
        scope=row.get('scope','auto')
        target=None
        if enabled and scope!='global':
            if scope=='auto':
                if person_index>=len(reference_ids):
                    raise ValueError('LoRAの自動割当先がありません。余分なLoRAは適用先を「全体」にするか解除してください。')
                target=reference_ids[person_index]
            else:
                target=int(scope.split(':')[1])
                if target not in reference_ids:
                    raise ValueError(f'LoRAの適用先：画像{target}を選び直してください。')
            person_index+=1
        resolved.append(dict(row,reference_id=target))
    return resolved


def global_loras(rows):
    return [row for row in rows if row['reference_id'] is None]


def strip_counts(text):
    text=re.sub(r'\b(?:one|two|three|four|[1-4])\s+(?:distinct\s+|separate\s+)?(?:people|persons?|characters?)\b','',text,flags=re.I)
    text=re.sub(r'\b[1-4](?:girls?|boys?|people)\b','',text,flags=re.I)
    text=re.sub(r'\bexactly\b|\bseparate bodies\b','',text,flags=re.I)
    return re.sub(r'\s+',' ',text).strip(' ,')


def appearance(text):
    # Pose/framing from a source portrait must not override the requested new scene.
    excluded={'solo','portrait','close-up','close up','headshot','full body','full-body','upper body',
              'standing','sitting','kneeling','lying','looking at viewer','looking at camera',
              'front view','side view','from above','from below','top-down view','white background','simple background'}
    return ', '.join(part.strip() for part in text.split(',') if part.strip().casefold() not in excluded)


def enforce_count(result, count, people=()):
    words={2:'two',3:'three',4:'four'}
    final=dict(result)
    positive=[]
    for part in final['positive'].split(','):
        part=part.strip()
        if part.casefold() in ('solo','single person','one person','one character'):continue
        if part:positive.append(part)
    # Use count tags only when each independent caption explicitly identifies the type.
    types=[]
    for person in people:
        caption=person['positive'].casefold()
        girl=bool(re.search(r'\b(?:1girl|girl|woman|female)\b',caption))
        boy=bool(re.search(r'\b(?:1boy|boy|man|male)\b',caption))
        types.append('girl' if girl and not boy else 'boy' if boy and not girl else '')
    count_tags=[]
    if len(types)==count and all(types):
        for kind in ('girl','boy'):
            number=types.count(kind)
            if number:count_tags.append(str(number)+kind+('s' if number>1 else ''))
        positive=[re.sub(r'\b[1-4](?:girls?|boys?)\b','',part,flags=re.I).strip(' ,') for part in positive]
    final['positive']=', '.join([f'exactly {words[count]} distinct people',*count_tags,'separate bodies',*filter(None,positive)])
    final['negative']=', '.join(filter(None,[final['negative'],'solo, single person, merged characters, fused bodies, merged faces']))
    return final


def regional_text(scene, person, index, count):
    location=('left person' if index==0 else 'right person') if count==2 else f'person {index+1} from the left'
    return ', '.join(filter(None,[strip_counts(scene),location,appearance(person)]))


def regional_negative(text):
    return ', '.join(part.strip() for part in text.split(',')
                     if part.strip().casefold() not in ('solo','single person','one person'))
