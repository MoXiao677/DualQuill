"""Strict review validation; formatting tolerance never repairs review evidence."""
import json
import math
import re


def redact_review_text(text):
    """Defense in depth; the request layer also removes its actual active key."""
    text = re.sub(r'(?i)\bBearer\s+[^\s"\'<>]+', 'Bearer [REDACTED]', text)
    return re.sub(r'\bsk-[A-Za-z0-9_-]+', '[REDACTED]', text)


class _Pairs(list):
    pass


def _normalize(value, path='$'):
    if isinstance(value, _Pairs):
        result = {}
        for key, item in value:
            if key in result:
                raise ValueError(f'{path}: duplicate JSON key {key!r}')
            result[key] = _normalize(item, f'{path}[{key!r}]')
        return result
    if type(value) is list:
        return [_normalize(item, f'{path}[{index}]') for index, item in enumerate(value)]
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f'{path}: nonfinite JSON number is not allowed')
    return value


def review_evidence(body):
    if type(body) is not str:
        raise ValueError('body: expected text')
    return [
        {'id': f'P{index}', 'text': line}
        for index, line in enumerate((line for line in body.splitlines() if line.strip()), start=1)
    ]


def parse_review_response(raw, body):
    if type(raw) is not str:
        raise ValueError('$: response must be text')
    text = raw.strip().removeprefix('\ufeff').strip()
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```', text, re.DOTALL | re.IGNORECASE)
        if match is None:
            raise ValueError('$: expected a single optional JSON fence, without surrounding commentary')
        text = match.group(1).strip().removeprefix('\ufeff').strip()
    try:
        result = _normalize(json.loads(text, object_pairs_hook=_Pairs))
    except json.JSONDecodeError as exc:
        raise ValueError(f'$: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}') from None
    if type(result) is not dict:
        raise ValueError('$: expected an object')
    for field, expected in (('passed', bool), ('issues', list)):
        if field not in result:
            raise ValueError(f'{field}: required field is missing')
        if type(result[field]) is not expected:
            raise ValueError(f'{field}: expected {expected.__name__}')
    evidence_by_id = {item['id']: item['text'] for item in review_evidence(body)}
    issues = []
    for index, issue in enumerate(result['issues']):
        path = f'issues[{index}]'
        if type(issue) is not dict:
            raise ValueError(f'{path}: expected an object')
        for field in ('severity', 'category', 'message'):
            if field not in issue:
                raise ValueError(f'{path}.{field}: required field is missing')
            if type(issue[field]) is not str or not issue[field].strip():
                raise ValueError(f'{path}.{field}: expected a nonempty string')
        for field, allowed in (('severity', ('blocking', 'major', 'minor')), ('category', ('continuity', 'style', 'logic', 'safety', 'other'))):
            if issue[field] not in allowed:
                raise ValueError(f'{path}.{field}: expected exactly one of {", ".join(allowed)}')
        has_id = 'evidence_id' in issue
        has_quote = 'evidence' in issue
        if not has_id and not has_quote:
            raise ValueError(f'{path}.evidence: required field evidence or evidence_id is missing')
        if has_id:
            evidence_id = issue['evidence_id']
            if type(evidence_id) is not str or not evidence_id.strip():
                raise ValueError(f'{path}.evidence_id: expected a nonempty string')
            if evidence_id not in evidence_by_id:
                raise ValueError(f'{path}.evidence_id: unknown evidence id {evidence_id!r}')
            paragraph = evidence_by_id[evidence_id]
            if has_quote:
                quote = issue['evidence']
                if type(quote) is not str or not quote.strip():
                    raise ValueError(f'{path}.evidence: expected a nonempty string')
                if quote not in paragraph:
                    raise ValueError(f'{path}.evidence: must be an exact substring of the selected evidence paragraph')
                normalized_evidence = quote
            else:
                normalized_evidence = paragraph
        else:
            evidence = issue['evidence']
            if type(evidence) is not str or not evidence.strip():
                raise ValueError(f'{path}.evidence: expected a nonempty string')
            if evidence not in body:
                raise ValueError(f'{path}.evidence: must be an exact nonempty substring of chapter body; no approximate matching')
            normalized_evidence = evidence
        issues.append(dict(severity=issue['severity'], category=issue['category'], evidence=normalized_evidence, message=issue['message']))
    blocking = any(issue['severity'] in ('blocking', 'major') for issue in issues)
    if result['passed'] != (not blocking):
        raise ValueError('passed: must be false when issues contain blocking/major, and true otherwise')
    return dict(passed=result['passed'], issues=issues)
