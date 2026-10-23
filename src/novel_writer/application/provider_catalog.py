"""Local implementation declarations and explicitly manual estimates, no live prices."""
from math import isfinite

def catalog():
    return dict(updated_at='2026-10-21',source='本地实现契约：domain/connections.py、application/custom_protocols.py；不是供应商能力保证或实时报价',
                price_status='unknown',currency=None,prices=None,
                protocols=[dict(id=name,model_discovery='显式请求模型列表；失败保留手工模型编号',
                                parameters=['temperature (可显式省略)','max_tokens']+(['max_completion_tokens'] if name=='openai-chat' else [])+['top_p','stop']+([] if name=='anthropic-messages' else ['seed']),sampling_support='当前连接与默认模型须显式声明；未知拒绝，覆盖模型不继承；逐模型原生profile可省略温度或选择Chat token字段；Messages top_p 模式不发送温度',streaming=True,streaming_mode='自建连接逐默认模型明确启用SSE，默认JSON；临时预览不持久化，合法终止后校验候选',
                                native_search=name=='gemini-content')
                           for name in ('openai-chat','anthropic-messages','gemini-content')],
                controls=dict(timeout_ms_max=300000,local_limits='逐连接最小间隔及每分钟上限；本进程内计数，重开清零；失败尝试也计数，不自动重试',
                              unsupported=['Messages seed','SSE公开搜索','自动重试']),
                note='模型名称、上下文上限、质量、供应商真实计价均未知；模型列表不证明生成可用。手工估价不会改变执行预算或授予请求许可。')

def estimate(values):
    fields={'input_tokens','output_tokens','input_per_million','output_per_million','currency'}
    if set(values)!=fields:raise ValueError('手工估价字段不完整或含未知字段')
    for name in fields-{'currency'}:
        value=values[name]
        if type(value) not in (int,float) or not isfinite(value) or not 0<=value<=1e12:raise ValueError('估价只接受有限非负数值')
    for name in ('input_tokens','output_tokens'):
        if type(values[name]) is not int:raise ValueError('手工令牌数量必须是整数；不能用字符数冒充令牌数')
    currency=values['currency']
    if type(currency) is not str or not 1<=len(currency)<=12 or not currency.isascii() or not currency.isalpha():raise ValueError('请输入币种字母代码')
    amount=(values['input_tokens']*values['input_per_million']+values['output_tokens']*values['output_per_million'])/1_000_000
    return dict(amount=amount,currency=currency.upper(),source='作者手工输入，未向供应商核实',price_status='manual_estimate',
                assumptions=values,model_request_sent=False,note='仅供估算，不是供应商报价或账单，不改变未知费用风险确认。')
