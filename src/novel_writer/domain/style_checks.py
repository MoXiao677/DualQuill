"""Versioned, literal style measurements; never a semantic quality judgement.

Specifications live in the existing six feature strings, so historical snapshots,
request hashes and backup/copy identities retain their original representation.
"""
import json
import math
import re
from novel_writer.domain.tasks import require
from novel_writer.storage.json_codec import strict_json_loads

FORMAT='style-checks-v1'
METRICS=('term_rate','forbidden_count','sentence_chars','dialogue_ratio')
CONTRACT=(' Each of the six card strings must encode JSON with exactly format="style-checks-v1", summary, checks. '
 'Each checks item has exactly metric, terms, min, max, evidence. Metrics: term_rate (literal occurrences per 1000 non-whitespace characters, for pronouns/imagery/particles), '
 'forbidden_count (literal count, min=max=0), sentence_chars (mean non-whitespace/non-sentence-delimiter characters per sentence), dialogue_ratio (characters inside Chinese curly quotes or ASCII double quotes / non-whitespace characters). '
 'terms is a list of nonempty literal strings, empty for sentence_chars/dialogue_ratio. min/max are finite nonnegative numbers, min<=max. '
 'Each check needs evidence with exactly start,end,quote, absolute Unicode offsets, quote exactly matching the supplied source. '
 'Give at least one check per feature, derive realistic ranges from samples; forbidden terms are proposed constraints, not evidence of absence. '
 'Use summary for the human explanation. Do not invent semantic metrics. Keep each encoded feature under 2000 characters.')


def specification(text):
    require(type(text) is str,'styles.invalid_feature_spec')
    if not text.lstrip().startswith('{'):
        return None
    value=strict_json_loads(text)
    require(type(value) is dict and set(value)=={'format','summary','checks'} and value['format']==FORMAT,'styles.invalid_feature_spec')
    require(type(value['summary']) is str and 0<len(value['summary'].strip())<=500 and type(value['checks']) is list and len(value['checks'])<=12,'styles.invalid_feature_spec')
    for check in value['checks']:
        require(type(check) is dict and set(check)=={'metric','terms','min','max','evidence'},'styles.invalid_feature_spec')
        metric=check['metric'];require(metric in METRICS,'styles.invalid_feature_metric')
        require(all(type(check[k]) in (int,float) and math.isfinite(check[k]) for k in ('min','max')) and 0<=check['min']<=check['max']<=100000,'styles.invalid_feature_range')
        terms=check['terms'];require(type(terms) is list and len(terms)<=20 and all(type(v) is str and 0<len(v.strip())<=40 for v in terms) and len(set(terms))==len(terms),'styles.invalid_feature_terms')
        require(bool(terms)==(metric in ('term_rate','forbidden_count')),'styles.invalid_feature_terms')
        if metric=='dialogue_ratio':require(check['max']<=1,'styles.invalid_feature_range')
        if metric=='forbidden_count':require(check['min']==check['max']==0,'styles.invalid_feature_range')
        evidence=check['evidence'];require(type(evidence) is list and 0<len(evidence)<=6,'styles.invalid_feature_evidence')
        for e in evidence:
            require(type(e) is dict and set(e)=={'start','end','quote'} and type(e['start']) is int and type(e['end']) is int and 0<=e['start']<e['end'] and type(e['quote']) is str and 0<len(e['quote'])<=200,'styles.invalid_feature_evidence')
    return value


def validate_features(card,source=None,ranges=None):
    for text in card.values():
        spec=specification(text)
        if spec is None:continue
        for check in spec['checks']:
            for e in check['evidence']:
                if source is not None:
                    require(e['end']<=len(source) and source[e['start']:e['end']]==e['quote'],'styles.invalid_feature_evidence')
                if ranges is not None:
                    require(any(start<=e['start']<e['end']<=end for start,end in ranges),'styles.invalid_feature_evidence')


def merge_features(cards):
    result={}
    for key in cards[0]:
        values=list(dict.fromkeys(card[key] for card in cards));specs=[specification(v) for v in values]
        if all(v is not None for v in specs):
            checks=[]
            for spec in specs:
                for check in spec['checks']:
                    if check not in checks:checks.append(check)
            result[key]=json.dumps(dict(format=FORMAT,summary='；'.join(dict.fromkeys(v['summary'] for v in specs)),checks=checks),ensure_ascii=False,separators=(',',':'))
        else:result[key]='\n'.join(values)
    return result


def generation_features(card):
    """Only targets and summaries go to trial providers, never source quotations."""
    result={}
    for key,text in card.items():
        spec=specification(text)
        result[key]=dict(summary=spec['summary'],checks=[{k:v for k,v in c.items() if k!='evidence'} for c in spec['checks']]) if spec else text
    return result


def evaluate(card,text):
    rows=[];denominator=sum(not c.isspace() for c in text)
    for feature,encoded in card.items():
        spec=specification(encoded)
        if not spec:continue
        for index,check in enumerate(spec['checks']):
            metric=check['metric'];spans=[]
            if metric in ('term_rate','forbidden_count'):
                for term in check['terms']:
                    spans.extend(dict(start=m.start(),end=m.end(),quote=m.group()) for m in re.finditer(re.escape(term),text))
                value=len(spans) if metric=='forbidden_count' else len(spans)*1000/max(1,denominator)
            elif metric=='sentence_chars':
                spans=[dict(start=m.start(),end=m.end(),quote=m.group()) for m in re.finditer(r'[^。！？!?\n.]+',text) if m.group().strip()]
                value=sum(sum(not c.isspace() for c in s['quote']) for s in spans)/max(1,len(spans))
            else:
                spans=[dict(start=m.start(),end=m.end(),quote=m.group()) for m in re.finditer(r'“[^”]*”|「[^」]*」|"[^"\n]*"',text)]
                value=sum(sum(not c.isspace() for c in s['quote'][1:-1]) for s in spans)/max(1,denominator)
            rows.append(dict(id=feature+'/'+str(index),feature=feature,summary=spec['summary'],metric=metric,terms=check['terms'],min=check['min'],max=check['max'],value=value,hit=bool(denominator and check['min']<=value<=check['max']),matches=spans[:100],match_count=len(spans)))
    return dict(version=FORMAT,status='measured' if rows else 'unquantified',checks=rows,semantic_quality_verified=False,method='字面词频/句界/引号统计；人称与意象仅检查指定词，不判断语义。位置为 Unicode 码点；命中不等于文风质量。')


def summarize(reports):
    rows=[]
    if reports:
        for check in reports[0]['checks']:
            values=[next(v for v in r['checks'] if v['id']==check['id']) for r in reports]
            hits=sum(v['hit'] for v in values);numbers=[v['value'] for v in values]
            rows.append(dict(id=check['id'],metric=check['metric'],hits=hits,samples=len(values),hit_rate=hits/len(values),value_min=min(numbers),value_max=max(numbers),value_range=max(numbers)-min(numbers),unstable=0<hits<len(values)))
    return dict(sample_count=len(reports),checks=rows,sufficient_samples=len(reports)>=2,semantic_quality_verified=False)
