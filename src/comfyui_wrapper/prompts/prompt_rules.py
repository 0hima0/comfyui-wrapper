"""Conservative tag conflicts: explicit UI prompts take precedence over hints."""
import re

COLORS = r'black|white|red|blue|green|yellow|pink|purple|brown|orange|grey|gray|silver|gold|blonde|blond'
GROUPS = [
    ('hair_length', ['short hair','medium hair','long hair','very long hair']),
    ('location', ['indoors','outdoors']),
    ('time', ['day','night','sunset','sunrise']),
    ('people', ['solo','multiple girls','multiple boys','group']),
    ('girls', ['1girl','2girls','3girls','4girls']),
    ('boys', ['1boy','2boys','3boys','4boys']),
    ('rating', ['safe','sensitive','nsfw','explicit']),
]


def tokens(text):
    return [t.strip() for t in text.split(',') if t.strip()]


def canonical(text):
    text = text.lower().strip().replace('_',' ')
    match = re.fullmatch(r'\((.*):\s*[0-9.]+\)', text)
    if match:
        text = match.group(1).strip()
    return ' '.join(text.split())


def attributes(token):
    name = canonical(token)
    result = {}
    for group,values in GROUPS:
        if name in values:
            result[group] = name
    # Distinguish objects, so blue dress does not remove white shirt.
    for color,subject in re.findall(r'\b('+COLORS+r') (hair|eyes|dress|shirt|skirt|jacket|coat|pants|shoes)\b',name):
        result[subject+'_color'] = {'gray':'grey','blonde':'blond'}.get(color,color)
    match=re.fullmatch(r'(very long|long|medium|short) (?:\w+ )?hair',name)
    if match:
        result['hair_length'] = match.group(1)+' hair'
    return result


def filter_candidates(text, positive, negative):
    wishes = [attributes(t) for t in tokens(positive)]
    excluded = {canonical(t) for t in tokens(negative)}
    keep,removed = [],[]
    for token in tokens(text):
        attrs = attributes(token)
        reason = ''
        if canonical(token) in excluded:
            reason = 'UI Negativeと一致'
        elif any(any(key in wish and wish[key] != value for key,value in attrs.items()) for wish in wishes):
            reason = 'UI Positiveと属性が競合'
        if reason:
            removed.append({'tag':token,'reason':reason})
        else:
            keep.append(token)
    return ', '.join(keep),removed


def merge_prompts(result, positive, negative):
    final = dict(result)
    # The explicit positive is authoritative over generated negative terms.
    positive_names = {canonical(t) for t in tokens(positive)}
    base,removed = filter_candidates(result['positive'],positive,negative)
    neg = [t for t in tokens(result['negative']) if canonical(t) not in positive_names]
    def join(base, extra):
        extra_names = {canonical(t) for t in tokens(extra)}
        return ', '.join([t for t in tokens(base) if canonical(t) not in extra_names]+tokens(extra))
    final['positive'] = join(base,positive)
    final['negative'] = join(', '.join(neg),negative)
    return final,removed
