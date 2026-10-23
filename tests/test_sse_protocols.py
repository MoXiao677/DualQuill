"""Incremental protocol tests use fictional wire bytes only."""
import json,unittest
from novel_writer.application.sse_protocols import StreamDecoder,StreamFailure

def event(value,name=None):
    return ((('event: '+name+'\r\n') if name else '')+'data: '+json.dumps(value,ensure_ascii=False)+'\r\n\r\n').encode()

def chat(text='',finish=None):
    return dict(id='fake',model='fiction',choices=[dict(index=0,delta=dict(role='assistant',content=text),finish_reason=finish)])

class SSETests(unittest.TestCase):
    def test_chat_every_byte_unicode_bom_crlf_usage_and_done(self):
        snapshots=[];d=StreamDecoder('openai-chat',100,'fictional-secret',snapshots.append)
        wire=b'\xef\xbb\xbf: comment\r\n\r\n'+event(chat('你好🙂'))+event(chat('', 'stop'))+event(dict(choices=[],usage=dict(prompt_tokens=3,completion_tokens=2,total_tokens=5)))+b'data: [DONE]\r\n\r\n'
        for byte in wire:d.feed(bytes([byte]))
        result=d.finish();self.assertEqual(result['choices'][0]['message']['content'],'你好🙂');self.assertEqual(result['usage']['total_tokens'],5);self.assertEqual(snapshots[-1],'你好🙂')
    def test_unfinished_event_or_missing_termination_is_failure(self):
        for wire in (event(chat('x')),event(chat('x','stop'))+b'data: [DONE]\n',event(chat('x'))+b'data: [DONE]\n\n'):
            with self.subTest(wire=wire),self.assertRaises(StreamFailure):
                d=StreamDecoder('openai-chat',100,'',lambda _:None);d.feed(wire);d.finish()
    def test_secret_split_never_published_and_clears(self):
        seen=[];d=StreamDecoder('openai-chat',100,'fake-key-123',seen.append)
        d.feed(event(chat('safe fake-')));self.assertEqual(seen[-1],'safe ')
        d.feed(event(chat('key-')))
        with self.assertRaises(StreamFailure):d.feed(event(chat('123')))
        self.assertTrue(all('fake-' not in v for v in seen));self.assertEqual(seen[-1],'')
    def test_invalid_utf8_tool_overlength_and_noncomplete(self):
        cases=[b'data: \xff\n\n',event(dict(choices=[dict(index=0,delta=dict(tool_calls=[{}]),finish_reason=None)])),event(chat('abcdef')),event(chat('x','length'))]
        for wire in cases:
            with self.subTest(wire=wire),self.assertRaises(StreamFailure):StreamDecoder('openai-chat',5,'',lambda _:None).feed(wire)
    def test_messages_text_and_legal_lifecycle(self):
        d=StreamDecoder('anthropic-messages',100,'',lambda _:None)
        frames=[('message_start',dict(message=dict(id='fake',model='fiction',role='assistant',content=[],usage=dict(input_tokens=4,output_tokens=0)))),('content_block_start',dict(index=0,content_block=dict(type='text',text=''))),('content_block_delta',dict(index=0,delta=dict(type='text_delta',text='你好'))),('content_block_stop',dict(index=0)),('message_delta',dict(delta=dict(stop_reason='end_turn'),usage=dict(output_tokens=2))),('message_stop',{})]
        for name,v in frames:d.feed(event(dict(type=name,**v),name))
        self.assertEqual(d.finish()['choices'][0]['message']['content'],'你好')
    def test_gemini_stop_and_no_auto_continuation(self):
        for reason in ('STOP','MAX_TOKENS','CONTINUATION'):
            d=StreamDecoder('gemini-content',100,'',lambda _:None)
            v=dict(candidates=[dict(index=0,content=dict(role='model',parts=[dict(text='你好')]),finishReason=reason)])
            if reason=='STOP':d.feed(event(v));self.assertEqual(d.finish()['choices'][0]['message']['content'],'你好')
            else:
                with self.assertRaises(StreamFailure):d.feed(event(v))
    def test_multiline_data_unknown_fields_and_lone_cr(self):
        d=StreamDecoder('openai-chat',100,'',lambda _:None)
        d.feed(b'ignored: yes\rid: 7\rdata: {"choices":\rdata: [{"index":0,"delta":{"content":"x"},"finish_reason":"stop"}]}\r\rdata: [DONE]\r\r')
        self.assertEqual(d.finish()['choices'][0]['message']['content'],'x')

    def test_gemini_usage_tail_after_stop_preserves_output_but_not_late_content(self):
        stop=event(dict(candidates=[dict(index=0,content=dict(role='model',parts=[dict(text='已完成🙂')] ),finishReason='STOP')]))
        for tail in (dict(candidates=[],usageMetadata=dict(promptTokenCount=17,candidatesTokenCount=23,totalTokenCount=40)),dict(usageMetadata=dict(promptTokenCount=17,candidatesTokenCount=23,totalTokenCount=40))):
            with self.subTest(tail=tail):
                d=StreamDecoder('gemini-content',100,'',lambda _:None);d.feed(stop+event(tail));result=d.finish()
                self.assertEqual(result['choices'][0]['message']['content'],'已完成🙂');self.assertEqual(result['usage']['total_tokens'],40)
        for tail in (dict(candidates=[]),dict(candidates=[dict(index=0,content=dict(parts=[dict(text='迟到续文')]))],usageMetadata=dict(totalTokenCount=40)),dict(candidates=[],usageMetadata=dict(totalTokenCount=-1))):
            with self.subTest(tail=tail),self.assertRaises(StreamFailure):
                d=StreamDecoder('gemini-content',100,'',lambda _:None);d.feed(stop+event(tail))
        with self.assertRaises(StreamFailure):
            d=StreamDecoder('gemini-content',100,'',lambda _:None);d.feed(event(dict(candidates=[],usageMetadata=dict(totalTokenCount=40))))
