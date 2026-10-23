"""Fictional localhost wire tests; never load a real profile or credential."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from novel_writer.application.provider_acceptance import (
    prepare, validate_plan, confirmation_template, quality_template, record_quality, execute)


KEY = 'fictional-loopback-key'
TEXT = '岚川把蓝色信封放回抽屉，决定等师父回来。'


def event(value, name=None):
    return ((('event: ' + name + '\n') if name else '') + 'data: ' + json.dumps(value, ensure_ascii=False) + '\n\n').encode('utf-8')


def wire(protocol, stream=False, *, thinking=False, usage=True):
    if protocol == 'openai-chat':
        if not stream:
            result = dict(id='fiction-request', model='fiction-model', choices=[dict(message=dict(role='assistant', content=TEXT), finish_reason='stop')], future_metadata=dict(additive=True))
            if usage:
                result['usage'] = dict(prompt_tokens=7, completion_tokens=3, total_tokens=10, prompt_tokens_details=dict(cached_tokens=2))
            return json.dumps(result, ensure_ascii=False).encode('utf-8')
        chunks = [dict(id='fiction-request', model='fiction-model', choices=[dict(index=0, delta=dict(role='assistant', content=TEXT), finish_reason=None)], future_metadata=True), dict(choices=[dict(index=0, delta={}, finish_reason='stop')])]
        if usage:
            chunks.append(dict(choices=[], usage=dict(prompt_tokens=7, completion_tokens=3, total_tokens=10)))
        return b''.join(event(v) for v in chunks) + b'data: [DONE]\n\n'
    if protocol == 'anthropic-messages':
        if not stream:
            content = ([dict(type='thinking', thinking='fictional private reasoning', signature='fiction-signature'), dict(type='redacted_thinking', data='fiction-opaque')] if thinking else []) + [dict(type='text', text=TEXT, citations=[])]
            result = dict(id='fiction-request', model='fiction-model', role='assistant', content=content, stop_reason='end_turn', future_metadata=True)
            if usage:
                result['usage'] = dict(input_tokens=7, output_tokens=3, cache_read_input_tokens=2)
            return json.dumps(result, ensure_ascii=False).encode('utf-8')
        frames = [('message_start', dict(message=dict(id='fiction-request', model='fiction-model', role='assistant', content=[], usage=dict(input_tokens=7, output_tokens=0)))), ('content_block_start', dict(index=0, content_block=dict(type='text', text=''))), ('content_block_delta', dict(index=0, delta=dict(type='text_delta', text=TEXT))), ('content_block_stop', dict(index=0)), ('message_delta', dict(delta=dict(stop_reason='end_turn'), usage=dict(output_tokens=3))), ('message_stop', {})]
        return b''.join(event(dict(type=name, future_metadata=True, **value), name) for name, value in frames)
    result = dict(responseId='fiction-request', modelVersion='fiction-model', candidates=[dict(index=0, content=dict(role='model', parts=[dict(text='fictional private reasoning', thought=True), dict(text=TEXT)]), finishReason='STOP')], future_metadata=True)
    if usage:
        result['usageMetadata'] = dict(promptTokenCount=7, candidatesTokenCount=3, totalTokenCount=14, thoughtsTokenCount=4, cachedContentTokenCount=2)
    return event(result) if stream else json.dumps(result, ensure_ascii=False).encode('utf-8')


class ProviderAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='provider-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.status = 200
        self.raw = b''
        self.content_type = 'application/json'
        self.pause = False
        self.truncated = False
        self.require_key = False
        self.received = threading.Event()
        self.release = threading.Event()
        owner = self

        class Supplier(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                owner.calls.append(dict(path=self.path, body=json.loads(raw), raw=raw, headers=dict(self.headers)))
                supplied = self.headers.get('Authorization', '').removeprefix('Bearer ') or self.headers.get('x-api-key') or self.headers.get('x-goog-api-key')
                status = 401 if owner.require_key and supplied != KEY else owner.status
                self.send_response(status)
                self.send_header('Content-Type', owner.content_type)
                self.send_header('Content-Length', str(len(owner.raw) + (20 if owner.truncated else 0)))
                if 300 <= owner.status < 400:
                    self.send_header('Location', '/redirect-target')
                self.end_headers()
                try:
                    if owner.pause:
                        owner.received.set()
                        owner.release.wait(3)
                    self.wfile.write(owner.raw)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        self.remote = ThreadingHTTPServer(('127.0.0.1', 0), Supplier)
        self.remote.daemon_threads = True
        self.thread = threading.Thread(target=self.remote.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.release.set()
        self.remote.shutdown()
        self.remote.server_close()
        self.thread.join(2)

    def plan(self, protocol='openai-chat', stream_mode='json', **kwargs):
        return prepare(protocol=protocol, base_url=f'http://127.0.0.1:{self.remote.server_port}/v1', model_id='fiction-model', evidence_directory=str(self.root), budget_limit=.01, currency='USD', stream_mode=stream_mode, **kwargs)

    def confirm(self, plan):
        return dict(confirmation_template(plan), confirm_external=True, accept_unknown_cost=True)

    def run_plan(self, plan, **kwargs):
        return execute(plan, self.confirm(plan), lambda: KEY, **kwargs)

    def test_three_protocols_json_and_sse_exact_wire_profiles_usage_and_additive_fields(self):
        for protocol in ('openai-chat', 'anthropic-messages', 'gemini-content'):
            for mode in ('json', 'sse'):
                with self.subTest(protocol=protocol, mode=mode):
                    self.raw = wire(protocol, mode == 'sse')
                    self.content_type = 'text/event-stream' if mode == 'sse' else 'application/json'
                    profile = dict(temperature_mode='omit')
                    if protocol == 'openai-chat':
                        profile['chat_token_field'] = 'max_completion_tokens'
                    plan = self.plan(protocol, mode, profile=profile)
                    result = self.run_plan(plan)
                    self.assertEqual(result['transport_status'], 'passed', result)
                    self.assertEqual(result['real_provider_calls'], 0)
                    self.assertEqual(result['quality_status'], 'not_assessed')
                    self.assertEqual(result['response']['output_text'], TEXT)
                    counts = result['response']['usage']
                    self.assertEqual(counts, dict(prompt_tokens=7, completion_tokens=3, total_tokens=14 if protocol == 'gemini-content' else 10))
                    sent = self.calls[-1]
                    self.assertEqual(sent['raw'].decode('utf-8'), plan['request_body'])
                    self.assertEqual(sent['path'], plan['path'])
                    body = sent['body']
                    if protocol == 'openai-chat':
                        self.assertEqual(sent['headers']['Authorization'], 'Bearer ' + KEY)
                        self.assertIn('max_completion_tokens', body)
                        self.assertNotIn('max_tokens', body)
                        self.assertNotIn('temperature', body)
                        self.assertEqual(body['stream'], mode == 'sse')
                    elif protocol == 'anthropic-messages':
                        self.assertEqual(sent['headers']['x-api-key'], KEY)
                        self.assertEqual(sent['headers']['anthropic-version'], '2023-06-01')
                        self.assertIn('system', body)
                        self.assertEqual(body['messages'][0]['role'], 'user')
                        self.assertNotIn('temperature', body)
                    else:
                        self.assertEqual(sent['headers']['x-goog-api-key'], KEY)
                        self.assertNotIn(KEY, sent['path'])
                        self.assertIn('streamGenerateContent?alt=sse' if mode == 'sse' else 'generateContent', sent['path'])
                        self.assertEqual(body['contents'][0]['role'], 'user')
                        self.assertNotIn('temperature', body['generationConfig'])
                    self.assertIsNone(result['diagnostic']['actual_cost'])
                    self.assertEqual(result['diagnostic']['cost_status'], 'unknown')
        self.assertEqual(len(self.calls), 6)

    def test_preview_and_cli_dry_run_never_resolve_or_read_credentials(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'accept_provider.py'
        spec = importlib.util.spec_from_file_location('accept_provider_test_cli', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch('socket.getaddrinfo', side_effect=AssertionError('dry-run resolved DNS')), patch('getpass.getpass', side_effect=AssertionError('dry-run read a key')):
            plan = self.plan()
            path = self.root / 'preview.json'
            path.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
            out = io.StringIO()
            with redirect_stdout(out):
                code = module.main(['run', '--plan', str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())['network_requests'], 0)
            self.assertFalse(list(self.root.glob('*.claim.json')))
            self.assertFalse(self.calls)

    def test_false_or_stale_confirmation_and_unknown_fields_reject_before_key_read(self):
        plan = self.plan()
        cases = [confirmation_template(plan), dict(self.confirm(plan), request_sha256='0' * 64), dict(self.confirm(plan), budget_limit=1), dict(self.confirm(plan), unknown=True)]
        for confirmation in cases:
            with self.assertRaises(ValueError):
                execute(plan, confirmation, lambda: self.fail('key read before valid consent'))
        for field, value in (('request_body', plan['request_body'] + ' '), ('model_id', 'other'), ('timeout_ms', 1234), ('unknown', True), ('scope', 'real-provider')):
            changed = dict(plan, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                execute(changed, self.confirm(plan), lambda: self.fail('tampered plan read key'))
        self.assertFalse(list(self.root.glob('*.claim.json')))
        self.assertFalse(self.calls)

    def test_confirmation_does_not_cover_new_valid_body_profile_budget_or_destination(self):
        original = self.plan()
        for change in (dict(sample_id='review'), dict(profile=dict(temperature_mode='omit')), dict(budget_limit=.02), dict(model_id='other')):
            fields = dict(protocol=original['protocol'], base_url=original['base_url'], model_id=original['model_id'], evidence_directory=str(self.root), budget_limit=.01, currency='USD', request_id=original['request_id'], created_at=original['created_at'])
            fields.update(change)
            changed = prepare(**fields)
            self.assertNotEqual(changed['request_sha256'], original['request_sha256'])
            with self.assertRaises(ValueError):
                execute(changed, self.confirm(original), lambda: self.fail('stale consent read key'))
        self.assertFalse(self.calls)

    def test_exclusive_claim_rejects_replay_and_concurrent_execution(self):
        self.raw = wire('openai-chat')
        plan = self.plan()
        self.assertEqual(self.run_plan(plan)['transport_status'], 'passed')
        with self.assertRaises(FileExistsError):
            execute(plan, self.confirm(plan), lambda: self.fail('replay read key'))
        self.assertEqual(len(self.calls), 1)
        claim = json.loads((self.root / (plan['request_id'] + '.claim.json')).read_text(encoding='utf-8'))
        result = json.loads((self.root / (plan['request_id'] + '.result.json')).read_text(encoding='utf-8'))
        self.assertEqual(claim['request_sha256'], result['request_sha256'])
        self.assertEqual(result['request_sha256'], plan['request_sha256'])

    def test_auth_permission_rate_limit_and_redirect_diagnostics_no_retry_or_key_echo(self):
        for protocol in ('openai-chat', 'anthropic-messages', 'gemini-content'):
            for mode in ('json', 'sse'):
                for status, category in ((401, 'authentication'), (403, 'permission'), (429, 'provider_rate_limit'), (307, 'redirect_rejected')):
                    with self.subTest(protocol=protocol, mode=mode, status=status):
                        self.status = status
                        self.raw = json.dumps(dict(error=KEY)).encode()
                        result = self.run_plan(self.plan(protocol, mode))
                        self.assertEqual(result['transport_status'], 'failed')
                        self.assertEqual(result['diagnostic']['category'], category)
                        self.assertFalse(result['diagnostic']['retry_automatically'])
                        self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(len(self.calls), 24)
        self.assertTrue(all(c['path'] != '/redirect-target' for c in self.calls))

    def test_all_protocols_wrong_fictional_key_rejected_by_actual_http_server(self):
        self.require_key = True
        self.raw = b'{"error":"fictional invalid credential"}'
        for protocol in ('openai-chat', 'anthropic-messages', 'gemini-content'):
            plan = self.plan(protocol)
            result = execute(plan, self.confirm(plan), lambda: 'fictional-wrong-key')
            self.assertEqual(result['response']['http_status'], 401)
            self.assertEqual(result['diagnostic']['category'], 'authentication')
            self.assertNotIn('fictional-wrong-key', json.dumps(result))
        self.assertEqual(len(self.calls), 3)

    def test_cancel_and_timeout_interrupt_real_socket_without_late_pass(self):
        self.pause = True
        self.raw = wire('openai-chat', True)
        self.content_type = 'text/event-stream'
        token = threading.Event()
        values = []
        worker = threading.Thread(target=lambda: values.append(self.run_plan(self.plan(stream_mode='sse', timeout_ms=2000), event=token)))
        worker.start()
        self.assertTrue(self.received.wait(2))
        begin = time.monotonic()
        token.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - begin, 1)
        self.assertEqual(values[0]['diagnostic']['category'], 'cancelled')
        result = self.run_plan(self.plan(stream_mode='sse', timeout_ms=150))
        self.assertEqual(result['diagnostic']['category'], 'timeout')
        self.assertEqual(result['transport_status'], 'failed')
        self.release.set()
        self.assertEqual(len(self.calls), 2)

    def test_pre_cancelled_does_not_consume_or_read_key(self):
        plan = self.plan()
        token = threading.Event()
        token.set()
        with self.assertRaises(ValueError):
            execute(plan, self.confirm(plan), lambda: self.fail('cancelled read key'), event=token)
        self.assertFalse(self.calls)
        self.assertFalse(list(self.root.glob('*.claim.json')))

    def test_missing_usage_is_unknown_not_zero_and_truncated_json_rejected(self):
        self.raw = wire('openai-chat', usage=False)
        result = self.run_plan(self.plan())
        self.assertEqual(result['response']['usage'], dict(prompt_tokens=None, completion_tokens=None, total_tokens=None))
        self.assertIsNone(result['diagnostic']['actual_cost'])
        self.truncated = True
        result = self.run_plan(self.plan())
        self.assertEqual(result['transport_status'], 'failed')
        self.assertEqual(result['response']['error_code'], 'response_truncated')

    def test_malformed_usage_is_rejected_instead_of_coerced_to_zero(self):
        payload = json.loads(wire('openai-chat'))
        for value in (-1, True, '12'):
            payload['usage']['prompt_tokens'] = value
            self.raw = json.dumps(payload).encode()
            result = self.run_plan(self.plan())
            self.assertEqual(result['transport_status'], 'failed')
            self.assertEqual(result['response']['error_code'], 'invalid_response_structure')

    def test_profile_and_scope_reject_unknown_or_unsafe_values(self):
        for profile in ({'unknown': True}, {'temperature_mode': 'auto'}, {'chat_token_field': 'other'}):
            with self.assertRaises(ValueError):
                self.plan(profile=profile)
        with self.assertRaises(ValueError):
            self.plan('anthropic-messages', profile=dict(chat_token_field='max_completion_tokens'))
        fields = dict(protocol='openai-chat', model_id='fiction', evidence_directory=str(self.root), budget_limit=.01, currency='USD')
        for url in ('https://example.com/v1', 'http://192.168.1.1/v1'):
            with self.assertRaises(ValueError):
                prepare(**fields, base_url=url)
        with self.assertRaises(ValueError):
            prepare(**fields, base_url=f'http://127.0.0.1:{self.remote.server_port}', scope='real-provider')

    def test_quality_template_never_auto_scores_transport(self):
        for sample_id in ('writing', 'summary', 'review'):
            value = quality_template(self.plan(sample_id=sample_id))
            self.assertEqual(value['status'], 'not_assessed')
            self.assertTrue(all(score['score'] is None for score in value['scores']))
            self.assertEqual(len(value['scores']), 5)

    def test_messages_json_thinking_metadata_is_not_output_or_tool_permission(self):
        self.raw = wire('anthropic-messages', thinking=True)
        result = self.run_plan(self.plan('anthropic-messages'))
        self.assertEqual(result['transport_status'], 'passed', result)
        self.assertEqual(result['response']['output_text'], TEXT)

    def test_gemini_sse_terminal_usage_frame_preserves_reported_total(self):
        value = json.loads(wire('gemini-content'))
        usage = value.pop('usageMetadata')
        self.content_type = 'text/event-stream'
        self.raw = event(value) + event(dict(usageMetadata=usage, future_metadata=True))
        result = self.run_plan(self.plan('gemini-content', 'sse'))
        self.assertEqual(result['transport_status'], 'passed', result)
        self.assertEqual(result['response']['usage']['total_tokens'], 14)

    def test_gemini_unreported_reasoning_total_stays_unknown(self):
        for stream in (False, True):
            value = json.loads(wire('gemini-content'))
            del value['usageMetadata']['totalTokenCount']
            self.raw = event(value) if stream else json.dumps(value).encode()
            self.content_type = 'text/event-stream' if stream else 'application/json'
            result = self.run_plan(self.plan('gemini-content', 'sse' if stream else 'json'))
            self.assertEqual(result['transport_status'], 'passed', result)
            self.assertIsNone(result['response']['usage']['total_tokens'])

    def test_gemini_usage_without_stop_duplicate_trailer_and_late_text_rejected(self):
        value = json.loads(wire('gemini-content'))
        trailer = event(dict(usageMetadata=value['usageMetadata']))
        self.content_type = 'text/event-stream'
        for raw in (trailer, event(value) + trailer + trailer, event(value) + trailer + event(value)):
            self.raw = raw
            self.assertEqual(self.run_plan(self.plan('gemini-content', 'sse'))['transport_status'], 'failed')

    def test_messages_unknown_tools_malformed_thinking_and_thinking_only_rejected(self):
        for content in ([dict(type='tool_use', id='fiction-tool', name='write_novel', input={})], [dict(type='unknown', text=TEXT)], [dict(type='thinking', thinking=42, signature='x'), dict(type='text', text=TEXT)], [dict(type='thinking', thinking='only thought', signature='x')]):
            self.raw = json.dumps(dict(role='assistant', content=content, stop_reason='end_turn')).encode()
            result = self.run_plan(self.plan('anthropic-messages'))
            self.assertEqual(result['transport_status'], 'failed')

    def test_gemini_mixed_media_tools_wrong_role_block_and_thought_flag_rejected(self):
        for mutation in ('inlineData', 'fileData', 'functionCall', 'wrong-role', 'blocked', 'thought-string'):
            value = json.loads(wire('gemini-content'))
            if mutation == 'wrong-role':
                value['candidates'][0]['content']['role'] = 'user'
            elif mutation == 'blocked':
                value['promptFeedback'] = dict(blockReason='SAFETY')
            elif mutation == 'thought-string':
                value['candidates'][0]['content']['parts'][1]['thought'] = 'false'
            else:
                value['candidates'][0]['content']['parts'][1][mutation] = {}
            self.raw = json.dumps(value).encode()
            self.assertEqual(self.run_plan(self.plan('gemini-content'))['transport_status'], 'failed')

    def test_chat_null_optional_metadata_allowed_but_refusal_not_success(self):
        value = json.loads(wire('openai-chat'))
        value['choices'][0]['message']['refusal'] = None
        self.raw = json.dumps(value).encode()
        self.assertEqual(self.run_plan(self.plan())['transport_status'], 'passed')
        value['choices'][0]['message']['refusal'] = 'fictional refusal'
        self.raw = json.dumps(value).encode()
        self.assertEqual(self.run_plan(self.plan())['transport_status'], 'failed')
        self.content_type = 'text/event-stream'
        self.raw = event(dict(choices=[dict(index=0, delta=dict(role='assistant', content=TEXT, refusal=None, tool_calls=None), finish_reason='stop')])) + b'data: [DONE]\n\n'
        self.assertEqual(self.run_plan(self.plan(stream_mode='sse'))['transport_status'], 'passed')

    def test_human_quality_is_append_only_bound_to_output_and_exact_quotes(self):
        self.raw = wire('openai-chat')
        plan = self.plan()
        result = self.run_plan(plan)
        score = quality_template(plan)
        score.update(status='human_reviewed', reviewer='fictional-test-reviewer', output_sha256=result['output_sha256'])
        for item in score['scores']:
            item.update(score=2, evidence='蓝色信封')
        first = record_quality(plan, result, score)
        second = record_quality(plan, result, score)
        self.assertNotEqual(first['review_id'], second['review_id'])
        self.assertEqual(first['semantic_acceptance'], 'author_decision_required')
        self.assertEqual(len(list(self.root.glob('*.quality-review.*.json'))), 2)
        self.assertEqual(result['quality_status'], 'not_assessed')
        invalid = deepcopy(score)
        invalid['scores'][0]['evidence'] = '未在输出出现的虚构引文'
        with self.assertRaises(ValueError):
            record_quality(plan, result, invalid)
        invalid = deepcopy(score)
        invalid['scores'][0]['score'] = True
        with self.assertRaises(ValueError):
            record_quality(plan, result, invalid)
        tampered = deepcopy(result)
        tampered['response']['output_text'] += '改动'
        with self.assertRaises(ValueError):
            record_quality(plan, tampered, score)
        self.assertEqual(len(self.calls), 1)

    def test_key_failure_claim_is_spent_and_exception_never_echoed(self):
        plan = self.plan()
        def failing_supplier():
            raise ValueError(KEY)
        result = execute(plan, self.confirm(plan), failing_supplier)
        self.assertEqual(result['request_attempts'], 0)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertFalse(self.calls)
        with self.assertRaises(FileExistsError):
            self.run_plan(plan)

    def test_claim_is_atomic_under_two_competing_threads(self):
        self.raw = wire('openai-chat')
        plan = self.plan()
        preview = self.root / (plan['request_id'] + '.preview.json')
        preview.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        barrier = threading.Barrier(2)
        outcomes = []
        def compete():
            barrier.wait()
            try:
                outcomes.append(self.run_plan(plan)['transport_status'])
            except FileExistsError:
                outcomes.append('already_spent')
        workers = [threading.Thread(target=compete) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertCountEqual(outcomes, ['passed', 'already_spent'])
        self.assertEqual(len(self.calls), 1)

    def test_cli_prepare_execute_dry_run_and_replay_use_same_frozen_files(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'accept_provider.py'
        spec = importlib.util.spec_from_file_location('accept_provider_test_full_cli', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out = io.StringIO()
        with redirect_stdout(out):
            code = module.main(['prepare', '--protocol', 'openai-chat', '--base-url', f'http://127.0.0.1:{self.remote.server_port}/v1', '--model', 'fiction-model', '--evidence-directory', str(self.root), '--budget', '.01', '--currency', 'USD', '--omit-temperature'])
        self.assertEqual(code, 0)
        plan = json.loads(out.getvalue())['preview']
        preview = self.root / (plan['request_id'] + '.preview.json')
        confirmation = self.root / (plan['request_id'] + '.confirmation.json')
        saved = json.loads(confirmation.read_text(encoding='utf-8'))
        self.assertFalse(saved['confirm_external'])
        self.assertFalse(self.calls)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(['run', '--plan', str(preview), '--dry-run']), 0)
        self.assertFalse(self.calls)
        saved.update(confirm_external=True, accept_unknown_cost=True)
        confirmation.write_text(json.dumps(saved), encoding='utf-8')
        self.raw = wire('openai-chat')
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            args = ['run', '--plan', str(preview), '--execute', '--confirmation', str(confirmation)]
            self.assertEqual(module.main(args), 0)
            self.assertEqual(module.main(args), 2)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((self.root / (plan['request_id'] + '.result.json')).exists())

    def test_key_input_fails_closed_without_tty_and_never_echoes_fallback(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'accept_provider.py'
        spec = importlib.util.spec_from_file_location('accept_provider_secure_key_cli', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.sys.stdin, 'isatty', return_value=False), patch.object(module.getpass, 'getpass', side_effect=AssertionError('non-tty read key')):
            with self.assertRaises(ValueError):
                module.read_key()
        import warnings
        def insecure_fallback(*args):
            warnings.warn('fictional fallback', module.getpass.GetPassWarning)
            self.fail('fallback continued to key input')
        with patch.object(module.sys.stdin, 'isatty', return_value=True), patch.object(module.getpass, 'getpass', side_effect=insecure_fallback):
            with self.assertRaises(module.getpass.GetPassWarning):
                module.read_key()
        self.assertFalse(self.calls)

    def test_cancellation_during_key_acquisition_has_diagnosis_and_zero_dispatch(self):
        token = threading.Event()
        def supplier():
            token.set()
            return KEY
        plan = self.plan()
        result = execute(plan, self.confirm(plan), supplier, event=token)
        self.assertEqual(result['diagnostic']['category'], 'cancelled')
        self.assertEqual(result['request_attempts'], 0)
        self.assertFalse(result['diagnostic']['may_have_been_billed'])
        self.assertFalse(self.calls)

    def test_messages_sse_thinking_and_redacted_thinking_never_become_prose(self):
        frames = [('message_start', dict(message=dict(id='fiction-thinking', role='assistant', content=[]))), ('content_block_start', dict(index=0, content_block=dict(type='thinking', thinking=''))), ('content_block_delta', dict(index=0, delta=dict(type='thinking_delta', thinking='fictional private thought'))), ('content_block_delta', dict(index=0, delta=dict(type='signature_delta', signature='fiction-signature'))), ('content_block_stop', dict(index=0)), ('content_block_start', dict(index=1, content_block=dict(type='redacted_thinking', data='fiction-opaque'))), ('content_block_stop', dict(index=1)), ('content_block_start', dict(index=2, content_block=dict(type='text', text=TEXT))), ('content_block_stop', dict(index=2)), ('message_delta', dict(delta=dict(stop_reason='end_turn'))), ('message_stop', {})]
        self.raw = b''.join(event(dict(type=name, **value), name) for name, value in frames)
        self.content_type = 'text/event-stream'
        result = self.run_plan(self.plan('anthropic-messages', 'sse'))
        self.assertEqual(result['transport_status'], 'passed', result)
        self.assertEqual(result['response']['output_text'], TEXT)


if __name__ == '__main__':
    unittest.main()
