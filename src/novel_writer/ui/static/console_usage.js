import {escapeHTML as h} from './views.js';
export function renderActualUsage(usage){
 if(!usage)return '<p class="hint">实际用量暂无可读记录，费用未知。</p>';
 const counters=usage.reported_subtotals||{},value=name=>counters[name]===null||counters[name]===undefined?'未知':String(counters[name]);
 const missing=usage.unknown_usage_tasks??(['partial_or_unknown','unavailable'].includes(usage.status)?1:0);
 const requested=usage.cost_status==='not_requested'||usage.status==='not_requested';
 return '<section class="console-usage" aria-label="实际用量"><p>已记录发送尝试 '+h(usage.external_attempts??'未知')+' 次 · 供应商已报告输入 '+h(value('prompt_tokens'))+' / 输出 '+h(value('completion_tokens'))+' / 总计 '+h(value('total_tokens'))+' token</p><p class="hint">'+(requested?'尚未发送模型请求；暂无实际费用。':'实际费用未知；风险预算和手工价格估算不作为账单。')+(missing?' 有 '+h(missing)+' 个任务用量缺失或不完整，已报告小计不代表完整总量。':'')+'</p></section>';
}
