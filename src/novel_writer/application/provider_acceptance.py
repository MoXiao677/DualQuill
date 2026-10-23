"""Explicit, fictional, one-request provider acceptance; no stored credentials.

Preparing a request never resolves DNS or reads credentials. Execution requires a
content-bound confirmation and creates an exclusive claim before asking for a key.
This developer tool never writes a novel, a candidate, or a workspace permission.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import json
import math
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from novel_writer.domain.connections import request_payload, validate_endpoint
from novel_writer.storage.json_codec import strict_json_loads


SAMPLES = {
    'writing': {
        'system': '以下全部为虚构验收材料。仅输出中文故事正文，不使用工具，不声称执行现实操作。',
        'user': '虚构城市雾港。修钟学徒岚川不知道信封内容。请写120至180字：他在停摆的钟楼发现蓝色信封，决定先等师父回来。必须出现“蓝色信封”，不能揭露信封内容，不能增加死亡事件。',
        'criteria': ['遵守字数与必写项', '人物知识边界', '情节因果与连贯', '中文可读性', '无擅加死亡或工具行为'],
    },
    'summary': {
        'system': '以下是虚构文本验收。只依据所给文本，不添加事实。输出简短中文摘要并逐字引用一段依据。',
        'user': '原文：岚川在停摆的钟楼发现蓝色信封。他没有拆开，只把信封放回抽屉，决定等师父回来。请区分已经发生的动作与未来的决定，不推断信封内容。',
        'criteria': ['摘要忠于原文', '已发生与计划区分', '引用逐字可核对', '未知事实不补全', '中文可读性'],
    },
    'review': {
        'system': '仅审核虚构文本。输出待核实意见与双方逐字引文，不修改原文，不把意见称为事实。',
        'user': '来源：岚川没有拆开蓝色信封，也不知道里面的字。候选：岚川读完信后，准确说出了信中的三个人名。请指出知识状态冲突，引用来源与候选的原文；无法确定的部分标为待核实。',
        'criteria': ['发现知识状态冲突', '双侧引文逐字可核对', '不添加来源事实', '意见标记待核实', '无自动改稿'],
    },
}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return sha256(_json(value).encode('utf-8')).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def prepare(*, protocol, base_url, model_id, evidence_directory, budget_limit,
            currency, sample_id='writing', stream_mode='json', profile=None,
            timeout_ms=15000, max_tokens=256, max_output_chars=4000,
            scope='loopback', request_id=None, created_at=None):
    """Return the exact wire preview, with unknown cost explicitly represented."""
    _require(scope in ('loopback', 'real-provider'), '验收范围非法')
    parsed = validate_endpoint(base_url, allow_local=scope == 'loopback')
    if scope == 'loopback':
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname == 'localhost'
        _require(local, 'loopback验收只允许显式回环地址')
    _require(type(model_id) is str and 0 < len(model_id) <= 200 and all(ord(c) >= 32 for c in model_id), '模型编号非法')
    _require(type(budget_limit) in (int, float) and math.isfinite(budget_limit) and 0 < budget_limit <= 10000, '须有正数预算；本地不能保证账单硬封顶')
    _require(type(currency) is str and 1 <= len(currency) <= 12 and currency.isascii() and currency.isalpha(), '须明确预算币种')
    _require(sample_id in SAMPLES and stream_mode in ('json', 'sse'), '样本或流式模式非法')
    for value, lower, upper in ((timeout_ms, 100, 300000), (max_tokens, 128, 8192), (max_output_chars, 128, 100000)):
        _require(type(value) is int and lower <= value <= upper, '验收上限非法')
    profile = {} if profile is None else profile
    _require(type(profile) is dict and set(profile) <= {'temperature_mode', 'chat_token_field'}, '原生profile含未知字段')
    _require(profile.get('temperature_mode', 'configured') in ('configured', 'omit'), '温度profile非法')
    _require(profile.get('chat_token_field', 'max_tokens') in ('max_tokens', 'max_completion_tokens'), '输出令牌profile非法')
    _require(protocol == 'openai-chat' or profile.get('chat_token_field', 'max_tokens') == 'max_tokens', '原生输出字段仅适用Chat')
    sample = SAMPLES[sample_id]
    options = dict(model_id=model_id, temperature=0.2, max_tokens=max_tokens,
                   sampling=dict(top_p=None, seed=None, stop=[], **profile) if profile and (profile.get('temperature_mode') == 'omit' or profile.get('chat_token_field') == 'max_completion_tokens') else None,
                   destination=dict(stream_mode=stream_mode))
    body = request_payload(protocol, [dict(role='system', content=sample['system']), dict(role='user', content=sample['user'])], options)
    from novel_writer.application.custom_protocols import request_spec
    _, path, headers = request_spec(dict(protocol=protocol, base_url=base_url, allow_local=scope == 'loopback', model_id=model_id, api_key='[entered-after-confirmation]', stream_mode=stream_mode))
    identity = request_id or str(uuid4())
    _require(str(UUID(identity)) == identity, '验收请求身份非法')
    timestamp = created_at or _now()
    _require(type(timestamp) is str and datetime.fromisoformat(timestamp).tzinfo is not None, '验收时间须含时区')
    directory = Path(evidence_directory)
    _require(directory.is_absolute(), '证据目录须为绝对路径')
    plan = dict(schema_version=1, request_id=identity, created_at=timestamp,
                scope=scope, protocol=protocol, base_url=base_url, model_id=model_id,
                sample_id=sample_id, stream_mode=stream_mode, profile=profile,
                evidence_directory=str(directory.resolve()), timeout_ms=timeout_ms,
                max_tokens=max_tokens, max_output_chars=max_output_chars,
                budget_limit=budget_limit, currency=currency.upper(), cost_status='unknown',
                estimated_cost=None, max_requests=1, automatic_retries=0,
                method='POST', path=path, header_names=sorted(headers),
                credential_source='interactive_after_single_request_confirmation',
                request_body=_json(body), request_body_sha256=_digest(body),
                quality_status='not_assessed', criteria=list(sample['criteria']),
                implementation_sha256=implementation_digest())
    return dict(plan, request_sha256=_digest(plan))


def validate_plan(plan):
    _require(type(plan) is dict, '验收预览须为对象')
    keys = ('protocol', 'base_url', 'model_id', 'evidence_directory', 'budget_limit',
            'currency', 'sample_id', 'stream_mode', 'profile', 'timeout_ms',
            'max_tokens', 'max_output_chars', 'scope', 'request_id', 'created_at')
    _require(all(key in plan for key in keys), '验收预览不完整')
    rebuilt = prepare(**{key: plan[key] for key in keys})
    _require(_json(plan) == _json(rebuilt), '验收预览内容/摘要已改变或包含未知字段')
    return rebuilt


def implementation_digest():
    root = Path(__file__).resolve().parents[1]
    paths = ['application/provider_acceptance.py', 'application/custom_protocols.py',
             'application/model_adapter.py', 'application/sse_protocols.py',
             'application/task_protocol.py', 'domain/connections.py', 'domain/sampling.py']
    return _digest({path: sha256((root / path).read_bytes()).hexdigest() for path in paths})


def quality_template(plan):
    validate_plan(plan)
    return dict(request_id=plan['request_id'], request_sha256=plan['request_sha256'],
                status='not_assessed', output_sha256=None, reviewer=None,
                scale={'0': '未达到', '1': '严重问题', '2': '部分达到', '3': '达到', '4': '充分达到'},
                scores=[dict(criterion=value, score=None, evidence=None) for value in plan['criteria']],
                note='必须由人工核对实际输出与引文；传输成功不代表语义质量通过。')


def record_quality(plan, result, scorecard):
    """Append a human review bound to the actual result and exact output quotes."""
    validate_plan(plan)
    _require(type(result) is dict and result.get('request_id') == plan['request_id'] and result.get('request_sha256') == plan['request_sha256'], '评分与请求身份不符')
    _require(result.get('transport_status') == 'passed' and type(result.get('response')) is dict, '失败传输不能登记质量评分')
    result_body = {key: value for key, value in result.items() if key != 'result_sha256'}
    _require(result.get('result_sha256') == _digest(result_body), '验收结果摘要不符')
    template = quality_template(plan)
    _require(type(scorecard) is dict and set(scorecard) == set(template), '评分字段缺失或未知')
    for key in ('request_id', 'request_sha256', 'scale', 'note'):
        _require(scorecard[key] == template[key], '评分模板身份/量表已改变')
    _require(scorecard['status'] == 'human_reviewed', '须明确标记人工已审阅')
    _require(type(scorecard['reviewer']) is str and 0 < len(scorecard['reviewer'].strip()) <= 100, '须有人工审阅标识')
    output = result['response']['output_text']
    output_digest = sha256(output.encode('utf-8')).hexdigest()
    _require(scorecard['output_sha256'] == result.get('output_sha256') == output_digest, '评分须绑定确切输出')
    _require(type(scorecard['scores']) is list and len(scorecard['scores']) == len(plan['criteria']), '须逐项人工评分')
    for criterion, value in zip(plan['criteria'], scorecard['scores']):
        _require(type(value) is dict and set(value) == {'criterion', 'score', 'evidence'} and value['criterion'] == criterion, '评分项目不符')
        _require(type(value['score']) is int and 0 <= value['score'] <= 4, '人工评分须为0至4的整数')
        _require(type(value['evidence']) is str and bool(value['evidence'].strip()) and value['evidence'] in output, '人工评分须引用实际输出原文')
    review = dict(schema_version=1, review_id=str(uuid4()), recorded_at=_now(),
                  request_id=plan['request_id'], request_sha256=plan['request_sha256'],
                  result_sha256=result['result_sha256'], quality_status='human_review_recorded',
                  scorecard=scorecard, semantic_acceptance='author_decision_required')
    path = Path(plan['evidence_directory']) / (plan['request_id'] + '.quality-review.' + review['review_id'] + '.json')
    with path.open('x', encoding='utf-8') as handle:
        handle.write(_json(review))
    return review


def confirmation_template(plan):
    validate_plan(plan)
    return dict(request_id=plan['request_id'], request_sha256=plan['request_sha256'],
                confirm_external=False, accept_unknown_cost=False,
                budget_limit=plan['budget_limit'], currency=plan['currency'])


def diagnostic(response):
    code = response.error_code
    kind = {'provider_http_401': 'authentication', 'provider_http_403': 'permission',
            'provider_http_429': 'provider_rate_limit', 'cancelled': 'cancelled',
            'timeout': 'timeout'}.get(code)
    if code and code.startswith('provider_http_3'):
        kind = 'redirect_rejected'
    # Credential echo redaction can replace error_code; retain HTTP diagnosis.
    if response.http_status in (401, 403, 429):
        kind = {401: 'authentication', 403: 'permission', 429: 'provider_rate_limit'}[response.http_status]
    elif response.http_status is not None and 300 <= response.http_status < 400:
        kind = 'redirect_rejected'
    return dict(category=kind or ('success' if response.complete else 'protocol_or_transport'),
                retry_automatically=False, may_have_been_billed=True,
                cost_status='unknown', actual_cost=None)


def execute(plan, confirmation, key_supplier, *, event=None):
    """Consume exactly one explicit request; never retries, reads env, or lists models."""
    plan = validate_plan(plan)
    expected = dict(confirmation_template(plan), confirm_external=True, accept_unknown_cost=True)
    _require(type(confirmation) is dict and _json(confirmation) == _json(expected), '须逐请求明确确认精确内容、去向、profile、预算及未知费用')
    from novel_writer.application.custom_protocols import ConfiguredHttpTransport
    from novel_writer.application.task_protocol import CancellationToken, TaskCancelled, TaskTimeout
    event = event if event is not None else threading.Event()
    _require(not event.is_set(), '请求已取消；没有读取凭据或发送')
    directory = Path(plan['evidence_directory'])
    directory.mkdir(parents=True, exist_ok=True)
    preview = directory / (plan['request_id'] + '.preview.json')
    if preview.exists():
        _require(_json(strict_json_loads(preview.read_text(encoding='utf-8'))) == _json(plan), '已有证据预览内容不符')
    else:
        with preview.open('x', encoding='utf-8') as handle:
            handle.write(_json(plan))
    claim = directory / (plan['request_id'] + '.claim.json')
    # O_EXCL is cross-process and crash-safe: failed/cancelled attempts are spent.
    with claim.open('x', encoding='utf-8') as handle:
        handle.write(_json(dict(request_id=plan['request_id'], request_sha256=plan['request_sha256'], claimed_at=_now())))
    result = dict(schema_version=1, request_id=plan['request_id'], request_sha256=plan['request_sha256'],
                  scope=plan['scope'], started_at=_now(), model_id=plan['model_id'],
                  protocol=plan['protocol'], stream_mode=plan['stream_mode'],
                  request_attempts=0, quality_status='not_assessed', real_provider_calls=0)
    started = time.monotonic()
    try:
        token = CancellationToken(event, float('inf'))
        token.checkpoint()
        key = key_supplier()
        _require(type(key) is str and 0 < len(key) <= 4096 and all(ord(c) >= 32 for c in key), '凭据格式非法')
        _require(key not in _json(plan), '凭据不可出现在预览或模型编号中')
        token = CancellationToken(event, time.monotonic() + plan['timeout_ms'] / 1000)
        token.checkpoint()
        saved = dict(protocol=plan['protocol'], base_url=plan['base_url'], allow_local=plan['scope'] == 'loopback', model_id=plan['model_id'], api_key=key, stream_mode=plan['stream_mode'])
        result['request_attempts'] = 1
        result['real_provider_calls'] = int(plan['scope'] == 'real-provider')
        response = ConfiguredHttpTransport().send(SimpleNamespace(request_body=plan['request_body']), saved, token, plan['max_output_chars'])
        result.update(response=asdict(response), diagnostic=diagnostic(response),
                      transport_status='passed' if response.complete else 'failed',
                      output_sha256=sha256(response.output_text.encode('utf-8')).hexdigest())
    except (TaskCancelled, TaskTimeout) as failure:
        result.update(transport_status='failed', diagnostic=dict(category='cancelled' if isinstance(failure, TaskCancelled) else 'timeout', retry_automatically=False, cost_status='unknown', actual_cost=None, may_have_been_billed=bool(result['request_attempts'])))
    except Exception:
        # Exception messages may contain secrets. Persist only a stable category.
        result.update(transport_status='failed', diagnostic=dict(category='local_preflight_or_execution_failure', retry_automatically=False, cost_status='unknown', actual_cost=None, may_have_been_billed=bool(result['request_attempts'])))
    finally:
        result.update(finished_at=_now(), elapsed_ms=round((time.monotonic() - started) * 1000))
        result['result_sha256'] = _digest(result)
        with (directory / (plan['request_id'] + '.result.json')).open('x', encoding='utf-8') as handle:
            handle.write(_json(result))
    return result


def load_plan(path):
    return validate_plan(strict_json_loads(Path(path).read_text(encoding='utf-8')))
