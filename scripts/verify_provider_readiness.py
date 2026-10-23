"""Run scoped tests with an outbound socket guard and retained fictional evidence."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests'), str(ROOT)]
MODULES = ['test_provider_acceptance', 'test_custom_providers', 'test_sse_protocols',
           'test_native_request_profile', 'test_sampling_parameters',
           'test_provider_management', 'test_sse_tasks', 'test_configured_tasks',
           'test_provider_connections']


def dump_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def smoke(directory):
    from test_provider_acceptance import wire, KEY
    from novel_writer.application.provider_acceptance import prepare, execute, confirmation_template, quality_template
    state = dict(raw=b'', mode='json', calls=[])

    class Supplier(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            state['calls'].append(dict(path=self.path, body=body.decode('utf-8'), header_names=sorted(self.headers.keys())))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if state['mode'] == 'sse' else 'application/json')
            self.send_header('Content-Length', str(len(state['raw'])))
            self.end_headers()
            self.wfile.write(state['raw'])

    remote = ThreadingHTTPServer(('127.0.0.1', 0), Supplier)
    remote.daemon_threads = True
    worker = threading.Thread(target=remote.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    worker.start()
    cases = []
    try:
        for protocol in ('openai-chat', 'anthropic-messages', 'gemini-content'):
            for mode in ('json', 'sse'):
                state.update(raw=wire(protocol, mode == 'sse', thinking=protocol == 'anthropic-messages'), mode=mode)
                target = directory / protocol / mode
                target.mkdir(parents=True)
                profile = dict(temperature_mode='omit')
                if protocol == 'openai-chat':
                    profile['chat_token_field'] = 'max_completion_tokens'
                plan = prepare(protocol=protocol, base_url=f'http://127.0.0.1:{remote.server_port}/v1', model_id='fiction-model', evidence_directory=str(target), budget_limit=.01, currency='USD', stream_mode=mode, profile=profile)
                confirmation = dict(confirmation_template(plan), confirm_external=True, accept_unknown_cost=True)
                dump_new(target / (plan['request_id'] + '.confirmation.json'), confirmation)
                dump_new(target / (plan['request_id'] + '.quality.json'), quality_template(plan))
                result = execute(plan, confirmation, lambda: KEY)
                dump_new(target / (plan['request_id'] + '.wire.json'), state['calls'][-1])
                cases.append(dict(protocol=protocol, stream_mode=mode, request_id=plan['request_id'], transport_status=result['transport_status'], evidence_directory=str(target), real_provider_calls=result['real_provider_calls'], quality_status=result['quality_status']))
    finally:
        remote.shutdown()
        remote.server_close()
        worker.join(2)
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-directory', required=True)
    args = parser.parse_args(argv)
    directory = Path(args.evidence_directory)
    if not directory.is_absolute():
        parser.error('证据目录须为独立绝对路径')
    directory = directory / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8])
    directory.mkdir(parents=True)
    temporary = directory / 'tmp'
    temporary.mkdir()
    os.environ.update(TEMP=str(temporary), TMP=str(temporary), PYTHONDONTWRITEBYTECODE='1')
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(temporary)
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    blocked = []
    local_connections = []

    def checked(address):
        try:
            local = type(address) is tuple and ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            local = False
        if not local:
            blocked.append(repr(address))
            raise OSError('Provider readiness verifier blocks non-loopback sockets')
        local_connections.append(dict(host=address[0], port=address[1]))

    def connect(sock, address):
        checked(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        checked(address)
        return original_connect_ex(sock, address)

    sources = [ROOT / 'src' / 'novel_writer' / name for name in (
        'application/provider_acceptance.py', 'application/custom_protocols.py',
        'application/model_adapter.py', 'application/sse_protocols.py',
        'application/task_protocol.py', 'domain/connections.py', 'domain/sampling.py')]
    sources += [ROOT / 'scripts' / 'accept_provider.py', Path(__file__)]
    sources += [ROOT / 'tests' / (name + '.py') for name in MODULES]
    def hashes():
        return {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in sources}
    before = hashes()
    with patch.object(socket.socket, 'connect', connect), patch.object(socket.socket, 'connect_ex', connect_ex):
        suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
        with (directory / 'unittest.log').open('x', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        cases = smoke(directory / 'smoke')
    after = hashes()
    ok = result.wasSuccessful() and not blocked and before == after and all(case['transport_status'] == 'passed' for case in cases)
    report = dict(schema_version=1, status='passed' if ok else 'failed', scope='fictional-loopback-only',
                  real_provider_calls=0, semantic_quality='not_assessed',
                  automatic_confirmation_scope='fictional-loopback-fixtures-only',
                  tests_run=result.testsRun, test_failures=len(result.failures), test_errors=len(result.errors),
                  tests_skipped=len(result.skipped), module_groups=len(MODULES), modules=MODULES,
                  loopback_socket_connections=len(local_connections),
                  blocked_nonloopback_attempts=blocked, source_unchanged=before == after,
                  source_sha256=before, smoke_cases=cases, smoke_groups=len(cases),
                  log=str(directory / 'unittest.log'), finished_at=datetime.now(timezone.utc).isoformat())
    dump_new(directory / 'report.json', report)
    print(json.dumps(dict(status=report['status'], tests_run=result.testsRun, smoke_groups=len(cases), real_provider_calls=0, report=str(directory / 'report.json')), ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
