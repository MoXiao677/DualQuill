"""Fictional graph-only three-protocol SSE provider on a random loopback port."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import os
from pathlib import Path
from uuid import uuid4
from novel_writer.domain.connections import canonical_messages
from test_sse_protocols import event, chat

PROTOCOLS = ('openai-chat', 'anthropic-messages', 'gemini-content')


def frames(protocol, first, last):
    if protocol == 'openai-chat':
        head = event(chat(first))
        tail = event(chat(last)) + event(chat('', 'stop'))
        tail += event(dict(choices=[], usage=dict(prompt_tokens=17, completion_tokens=23, total_tokens=40)))
        tail += b'data: [DONE]\r\n\r\n'
    elif protocol == 'anthropic-messages':
        head = event(dict(type='message_start', message=dict(id='fiction-graph', role='assistant', content=[], usage=dict(input_tokens=17, output_tokens=0))), 'message_start')
        head += event(dict(type='content_block_start', index=0, content_block=dict(type='text', text='')), 'content_block_start')
        head += event(dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text=first)), 'content_block_delta')
        tail = event(dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text=last)), 'content_block_delta')
        tail += event(dict(type='content_block_stop', index=0), 'content_block_stop')
        tail += event(dict(type='message_delta', delta=dict(stop_reason='end_turn'), usage=dict(output_tokens=23)), 'message_delta')
        tail += event(dict(type='message_stop'), 'message_stop')
    else:
        head = event(dict(candidates=[dict(index=0, content=dict(role='model', parts=[dict(text=first)]))]))
        tail = event(dict(candidates=[dict(index=0, content=dict(role='model', parts=[dict(text=last)]), finishReason='STOP')]))
        # A metadata-only final frame must not discard a legally completed graph.
        tail += event(dict(candidates=[], usageMetadata=dict(promptTokenCount=17, candidatesTokenCount=23, totalTokenCount=40)))
    return head, tail


@contextmanager
def graph_sse_wire(protocol='openai-chat', outcome='success'):
    calls, ready, release, attempted, closed = [], threading.Event(), threading.Event(), threading.Event(), threading.Event()
    evidence = os.environ.get('GRAPH_SSE_EVIDENCE')
    evidence = Path(evidence) / (protocol+'-'+outcome+'-'+str(uuid4())+'.json') if evidence else None
    def record():
        if evidence:
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps(dict(protocol=protocol,outcome=outcome,calls=calls,
                head_flushed=ready.is_set(),tail_attempted=attempted.is_set(),handler_closed=closed.is_set(),
                real_provider_calls=0),ensure_ascii=False,indent=2),encoding='utf8')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            body = json.loads(raw)
            payload = json.loads(canonical_messages(body, protocol)[1]['content'])
            sources = payload['sources']
            evidence = [dict(source_index=i, start=0, end=len(s['text']), quote=s['text']) for i, s in enumerate(sources)]
            output = dict(overview='流式图谱待核实 <img src=x onerror="window.graphInjected=true">',
                nodes=[dict(key='a', kind='character', label='阿岚', aliases=['小岚'], evidence=evidence),
                       dict(key='b', kind='location', label='灯塔', aliases=['旧塔'], evidence=evidence[:1])],
                edges=[dict(from_key='a', to_key='b', relation='到达', evidence=evidence)])
            if outcome == 'quote':
                output['nodes'][0]['evidence'][0]['quote'] = '未保存的伪造引文'
            elif outcome == 'typed':
                output['nodes'][0]['kind'] = 'unsupported'
            elif outcome == 'missing':
                output['edges'][0]['evidence'] = []
            content = json.dumps(output, ensure_ascii=False)
            split = len(content) // 2
            head, tail = frames(protocol, content[:split], content[split:])
            if outcome == 'error':
                tail = event(dict(error=dict(message='fictional supplier failure')), 'error')
            elif outcome in ('truncated', 'disconnect'):
                tail = b''
            calls.append(dict(raw=raw.decode('utf8'), body=body, payload=payload, output=content, path=self.path,
                sse_head=head.decode('utf8'),sse_tail=tail.decode('utf8')))
            record()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            if outcome != 'truncated':
                self.send_header('Content-Length', str(len(head)+len(tail)+(20 if outcome=='disconnect' else 0)))
            self.end_headers()
            try:
                # Split every UTF-8 byte, including the emoji and SSE boundaries.
                for byte in head:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                ready.set()
                release.wait(10)
                attempted.set()
                self.wfile.write(tail)
                self.wfile.flush()
            except OSError:
                pass
            finally:
                ready.set()
                attempted.set()
                closed.set()
                record()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=.01), daemon=True)
    worker.start()
    try:
        yield dict(url='http://127.0.0.1:'+str(server.server_port)+'/v1', calls=calls,
                   ready=ready, release=release, attempted=attempted, closed=closed)
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(2)
        record()
