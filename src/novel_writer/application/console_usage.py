"""Read actual persisted provider usage, never estimate or infer an invoice."""
from copy import deepcopy


def actual_usage(detail):
    records=[];seen=set()
    sources=[detail.get(key,[]) for key in ('responses','model_results','late_results')]+[detail.get('writing',{}).get('late_results',[])]
    for source in sources:
        for record in source:
            response=record.get('response')
            if not isinstance(response,dict):continue
            identity=(record.get('attempt_id'),response.get('response_id'),response.get('raw_response'),json_usage(response.get('usage')))
            if identity in seen:continue
            seen.add(identity)
            usage=response.get('usage') or {}
            # Missing counters remain unknown; output limits/candidate lengths are not usage.
            values={name:usage.get(name) if type(usage.get(name)) is int and usage[name]>=0 else None
                    for name in ('prompt_tokens','completion_tokens','total_tokens')}
            records.append(dict(record_id=record.get('id'),attempt_id=record.get('attempt_id'),
                                response_id=response.get('response_id'),complete=response.get('complete'),
                                usage=values))
    attempts={event.get('attempt_id') or event.get('id') for event in detail.get('events',[]) if event.get('kind')=='started'}
    requested=bool(attempts or records)
    totals={name:sum(row['usage'][name] for row in records if row['usage'][name] is not None)
            if any(row['usage'][name] is not None for row in records) else None
            for name in ('prompt_tokens','completion_tokens','total_tokens')}
    complete=bool(records) and all(all(v is not None for v in row['usage'].values()) for row in records) and len(records)>=len(attempts)
    unknown=bool(detail.get('unavailable'))
    return dict(status='unavailable' if unknown else 'reported' if complete else 'partial_or_unknown' if requested else 'not_requested',
                external_attempts=None if unknown else len(attempts),reported_subtotals=totals,
                totals=deepcopy(totals) if complete else {name:None for name in totals},records=records,
                cost=dict(status='unknown' if requested or unknown else 'not_requested',amount=None,currency=None,
                          reason='任务状态不可读，无法确认实际用量或费用' if unknown else '供应商响应未提供已结算费用；风险预算和手工价格不是实际账单' if requested else '尚未发送模型请求'))


def json_usage(usage):
    return tuple((name,(usage or {}).get(name)) for name in ('prompt_tokens','completion_tokens','total_tokens'))


def usage_summary(items):
    usages=[value['usage'] for value in items if value.get('usage')]
    active=[value for value in usages if value['status']!='not_requested']
    totals={name:sum(value['reported_subtotals'][name] for value in active if value['reported_subtotals'][name] is not None)
            if any(value['reported_subtotals'][name] is not None for value in active) else None
            for name in ('prompt_tokens','completion_tokens','total_tokens')}
    return dict(task_count=len(usages),external_attempts=None if any(value['external_attempts'] is None for value in usages) else sum(value['external_attempts'] for value in usages),
                reported_subtotals=totals,unknown_usage_tasks=sum(value['status'] in ('partial_or_unknown','unavailable') for value in active),
                cost_status='unknown' if active else 'not_requested',actual_cost=None)
