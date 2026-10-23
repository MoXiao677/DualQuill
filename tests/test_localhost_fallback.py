"""Address fallback is before HTTP only, with every DNS answer validated first."""
import json,socket,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
import test_custom_providers as fixture
from novel_writer.application.custom_protocols import ConfiguredHttpTransport,connection_for
from novel_writer.application.task_protocol import CancellationToken

class LocalhostFallbackTests(unittest.TestCase):
    def test_ipv6_refusal_falls_back_to_ipv4_and_posts_only_once(self):
        with fixture.wire('openai-chat') as (endpoint,calls):
            port=urlsplit(endpoint).port;saved=dict(base_url='http://localhost:'+str(port)+'/v1',allow_local=True,protocol='openai-chat',api_key='fiction-localhost',model_id='fiction-model')
            answers=[(socket.AF_INET6,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('::1',port,0,0)),(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('127.0.0.1',port))]
            with patch('novel_writer.application.custom_protocols.socket.getaddrinfo',return_value=answers):
                response=ConfiguredHttpTransport().send(SimpleNamespace(request_body=json.dumps(dict(model='fiction-model',messages=[]))),saved,CancellationToken(threading.Event(),time.monotonic()+3),1000)
            self.assertTrue(response.complete,response);self.assertEqual(len(calls),1);self.assertEqual(response.output_text,'虚构协议候选')
    def test_disallowed_later_dns_answer_blocks_all_attempts(self):
        saved=dict(base_url='http://localhost:9/v1',allow_local=True)
        answers=[(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('127.0.0.1',9)),(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('10.0.0.1',9))]
        with patch('novel_writer.application.custom_protocols.socket.socket') as connector:
            with self.assertRaises(ValueError):connection_for(saved,1,_resolver=lambda *a,**k:answers)
            connector.assert_not_called()
    def test_http_failure_after_connection_is_never_retried_on_another_address(self):
        with fixture.wire('openai-chat',status=500) as (endpoint,calls):
            port=urlsplit(endpoint).port;saved=dict(base_url='http://localhost:'+str(port)+'/v1',allow_local=True,protocol='openai-chat',api_key='fiction-localhost',model_id='fiction-model')
            answers=[(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('127.0.0.1',port))]*2
            with patch('novel_writer.application.custom_protocols.socket.getaddrinfo',return_value=answers):
                response=ConfiguredHttpTransport().send(SimpleNamespace(request_body='{}'),saved,CancellationToken(threading.Event(),time.monotonic()+3),1000)
            self.assertFalse(response.complete);self.assertEqual(response.error_code,'provider_http_500');self.assertEqual(len(calls),1)
