"""Detect explicitly stored long execution limits without changing frozen records."""

def contains_long_timeout(value):
    if isinstance(value, dict):
        timeout = value.get('timeout_ms')
        return (type(timeout) is int and timeout > 30000) or any(contains_long_timeout(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_long_timeout(v) for v in value)
    return False
