"""Strict response validation with safe provider diagnostics."""

def chat_completion_text(data):
    """Return content only for normal stop completions without tool calls."""
    choice = data['choices'][0]
    reason = choice.get('finish_reason')
    allowed_reasons = {'stop', 'length', 'content_filter', 'tool_calls', 'function_call'}
    if reason is None:
        safe_reason = 'null'
    elif type(reason) is str and reason in allowed_reasons:
        safe_reason = reason
    else:
        safe_reason = 'unknown'

    message = choice['message']
    errors = []
    if safe_reason != 'stop':
        errors.append('finish_reason is not normal stop')
    if message.get('tool_calls') or message.get('function_call'):
        errors.append('unauthorized tools')
    if errors:
        raise ValueError(
            'Chat completion rejected: finish_reason=' + safe_reason
            + '; ' + '; '.join(errors)
        )
    return message['content']
