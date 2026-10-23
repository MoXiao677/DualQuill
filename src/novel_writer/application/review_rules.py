"""真实离线字面/结构化时间与基础查重；规则产物不是模型语义结论。"""
import re,unicodedata,datetime
from difflib import SequenceMatcher
from novel_writer.domain.review import *
from novel_writer.domain.tasks import parse,encode,require
from novel_writer.domain.memory import capture_source
from novel_writer.application.fields import check_fields
from novel_writer.application.task_protocol import AdapterResult

def canonical_request(raw):
    check_fields(raw,{'instruction','max_output_chars','timeout_ms','rules','selected_chapter_ids','previous_report_id'})
    require(set(raw)=={'instruction','max_output_chars','timeout_ms','rules','selected_chapter_ids','previous_report_id'},'审核参数缺失')
    raw={**raw,'rules':dict(raw['rules'])} if type(raw.get('rules')) is dict else raw
    if type(raw.get('rules')) is dict and type(raw['rules'].get('near_threshold')) is int:raw['rules']['near_threshold']=float(raw['rules']['near_threshold'])
    return encode(parse(AnalysisRequest,raw))
def prepare_parameters(state,raw):
    raw=canonical_request(raw)
    rules=parse(AuditRules,raw['rules']);ids=raw['selected_chapter_ids'];require(type(ids) is list and all(type(i) is str for i in ids),'审核章范围非法')
    chapters={c['id']:c for c in state['document']['chapters']};require(set(ids)<=set(chapters),'审核范围跨书/缺失')
    previous=raw['previous_report_id']
    if previous is not None:require(any(r['id']==previous for r in state.get('review_reports',[])),'复审报告不属于当前书')
    sources=[]
    for chapter in sorted((chapters[i] for i in ids),key=lambda c:c['number']):
        metadata=dict(project_id=state['document']['project']['id'],chapter_id=chapter['id'],chapter_number=chapter['number'],source_revision=state['revision'],title=chapter['title'])
        sig=capture_source(state,dict(kind='chapter',entity_id=chapter['id']))
        sources.append(AuditSource(kind='chapter',entity_id=chapter['id'],version_id=sig['version_id'],source_sha256=sig['source_sha256'],text=chapter['content'],status=chapter['status'],core_idea='',objective='',story_time='',character_ids=(),scenes=(),**metadata))
        if rules.check_timeline:
            outline=next((o for o in state['document']['chapter_outlines'] if o['chapter_id']==chapter['id']),None)
            if outline:
                scenes=tuple(parse(SceneSnapshot,s) for s in outline['scenes']);sig=capture_source(state,dict(kind='chapter_outline',entity_id=outline['id']))
                sources.append(AuditSource(kind='chapter_outline',entity_id=outline['id'],version_id=sig['version_id'],source_sha256=sig['source_sha256'],text=outline_text(outline['core_idea'],outline['objective'],outline['story_time'],scenes),status=outline['status'],core_idea=outline['core_idea'],objective=outline['objective'],story_time=outline['story_time'],character_ids=tuple(outline['character_ids']),scenes=scenes,**metadata))
    revoked={a['waiver_id'] for a in state.get('review_actions',[]) if a['kind']=='revoke_waiver'}
    waivers=tuple(parse(RuleWaiver,w) for w in state.get('rule_waivers',[]) if w['id'] not in revoked)
    return AnalysisParameters(instruction=raw['instruction'],max_output_chars=raw['max_output_chars'],timeout_ms=raw['timeout_ms'],rules=rules,selected_chapter_ids=tuple(ids),previous_report_id=previous,sources=tuple(sources),waivers=waivers)

def evidence(source,start,end,path='content'):
    quote=source.text[start:end]
    return Evidence(source_kind=source.kind,entity_id=source.entity_id,chapter_id=source.chapter_id,source_revision=source.source_revision,version_id=source.version_id,source_sha256=source.source_sha256,field_path=path,start=start,end=end,quote=quote,quote_sha256=text_digest(quote))
def normalized(text,mode):
    return ''.join(c for c in text if not c.isspace() and not(mode=='punctuation' and unicodedata.category(c).startswith('P')))
def ordinal(text):
    match=re.fullmatch(r'第([1-9][0-9]*)天',text)
    if match:return 'day',int(match[1])
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',text):return 'date',datetime.date.fromisoformat(text).toordinal()
    except ValueError:pass
    return None
def analyze(parameters,token):
    issues=[];proposals=[];fragments=[];limited=False;policy=policy_digest(parameters.rules)
    def add(rule,message,ev,score=None):
        nonlocal limited
        signatures=tuple(WaiverEvidence(source_kind=e.source_kind,entity_id=e.entity_id,field_path=e.field_path,quote_sha256=e.quote_sha256) for e in ev)
        if any(w.rule_id==rule and w.policy_sha256==policy and w.evidence==signatures for w in parameters.waivers):return
        if len(issues)>=80:limited=True;return
        issues.append(DetectedIssue(rule_id=rule,severity='error' if rule in ('forbidden_literal','missing_literal') else 'warning',message=message,evidence=tuple(ev),score=score))
    for source in parameters.sources:
        token.checkpoint()
        if source.kind=='chapter':
            for term in parameters.rules.forbidden_literals:
                offset=source.text.find(term)
                if offset>=0:add('forbidden_literal','命中作者指定禁用字面串：'+term,[evidence(source,offset,offset+len(term))])
            for term in parameters.rules.required_literals:
                if term not in source.text:add('missing_literal','所选章节未出现作者指定必需字面串：'+term,[evidence(source,0,0)])
            segments=[]
            for match in re.finditer(r'\S[^\n]*(?:\n(?!\s*\n)[^\n]+)*',source.text):
                start,end=match.span();text=source.text[start:end];norm=normalized(text,parameters.rules.normalization)
                if norm.strip():segments.append((source,start,end,norm))
            if segments:
                s,start,end,norm=segments[0]
                if len(proposals)<80:proposals.append(ProposalDraft(kind='chapter_summary',title='第'+str(source.chapter_number)+'章原文摘录',text=source.text[start:end],position_chapter_id=source.chapter_id,evidence=evidence(source,start,end),method='verbatim_excerpt'))
            fragments.extend(segment for segment in segments if len(segment[3])>=parameters.rules.minimum_fragment_chars)
        elif parameters.rules.check_timeline:
            previous=None
            for index,scene in sorted(enumerate(source.scenes),key=lambda p:p[1].order):
                token.checkpoint();current=ordinal(scene.story_time)
                path=f'scenes.{index}.story_time';start,end=outline_layout(source.core_idea,source.objective,source.story_time,source.scenes)[1][path]
                ev=evidence(source,start,end,path)
                if current is not None:
                    if previous and previous[0][0]==current[0] and previous[0][1]>current[1]:add('timeline_order','明确声明的场景时间随场景顺序倒退；仅检查声明值，不判断因果。',[previous[1],ev])
                    previous=(current,ev)
    if len(fragments)>160:limited=True;fragments=fragments[:160]
    pairs=0
    for i,left in enumerate(fragments):
        for right in fragments[i+1:]:
            token.checkpoint();pairs+=1
            if pairs>5000:limited=True;break
            a,b=left[3],right[3];ev=[evidence(left[0],left[1],left[2]),evidence(right[0],right[1],right[2])]
            if a==b:add('duplicate_exact','按声明归一规则精确重复；可能是合法引用/回环，须作者判断。',ev,1.0)
            elif max(len(a),len(b))<=2000 and min(len(a),len(b))/max(len(a),len(b))>=parameters.rules.near_threshold:
                score=SequenceMatcher(None,a,b,autojunk=False).ratio()
                if score>=parameters.rules.near_threshold:add('duplicate_near','SequenceMatcher字面基础近似；不是语义重复结论。',ev,float(score))
        if pairs>5000:break
    output=AuditOutput(issues=tuple(issues),proposals=tuple(proposals),limited=limited,limitations=('仅识别第N天/ISO日期的显式场景声明；其它时间不推断。','仅原文/结构字段摘录，不生成语义摘要或虚构事实。','字面/空白标点归一与基础相似度，不是语义/因果/全网审核。','最多80问题/80提案、160段及5000近似组合；超限明确标记。'))
    validate_output(output,parameters);return output

class OfflineAuditAdapter:
    adapter_id='offline-audit-rules-v1'
    def run(self,call,token):
        output=analyze(call.input.parameters,token)
        return AdapterResult(task_id=call.task_id,attempt_id=call.attempt_id,capability=call.capability,output_text=f'离线规则审核完成：{len(output.issues)}项问题，{len(output.proposals)}项原文/声明字段提案；非AI语义结论。',complete=True,analysis_output=output)
