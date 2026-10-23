import errno
import socketserver
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from novel_writer.application.custom_protocols import connection_for,ConfiguredHttpTransport
from novel_writer.application.task_protocol import CancellationToken,TaskCancelled

class CustomDeadlineTests(unittest.TestCase):
    def saved(self,base='http://127.0.0.1:31337/v1'):
        return dict(base_url=base,allow_local=True,protocol='openai-chat',api_key='fiction-time-key',model_id='fiction-model')
    def test_dns_time_is_subtracted_from_connect_budget(self):
        def dns(*args,**kwargs):time.sleep(.08);return [(2,1,6,'',('127.0.0.1',31337))]
        def old_blocking(*args,timeout,**kwargs):time.sleep(timeout);raise TimeoutError('controlled pending connect')
        class Pending:
            def setblocking(self,*args):pass
            def connect_ex(self,*args):return errno.EINPROGRESS
            def close(self):pass
        def pending_select(read,write,error,timeout):time.sleep(timeout);return [],[],[]
        with patch('socket.getaddrinfo',side_effect=dns),patch('socket.create_connection',side_effect=old_blocking),patch('socket.socket',return_value=Pending()),patch('select.select',side_effect=pending_select):
            started=time.monotonic();connection=connection_for(self.saved(),.18)
            with self.assertRaises(TimeoutError):connection.connect()
            elapsed=time.monotonic()-started;connection.close();self.assertLess(elapsed,.235,'connect reset the entire timeout after DNS')
    def test_cancel_interrupts_dns_wait_before_any_connect_or_body(self):
        def dns(*args,**kwargs):time.sleep(.5);return [(2,1,6,'',('127.0.0.1',31337))]
        event=threading.Event();timer=threading.Timer(.03,event.set);timer.start()
        try:
            with patch('socket.getaddrinfo',side_effect=dns),patch('socket.create_connection') as connect:
                started=time.monotonic()
                try:ConfiguredHttpTransport().send(SimpleNamespace(request_body='{"fiction":"must not send"}'),self.saved(),CancellationToken(event,time.monotonic()+1),1000)
                except TaskCancelled:pass
                self.assertLess(time.monotonic()-started,.2,'cancellation waited for DNS');connect.assert_not_called()
        finally:timer.cancel();timer.join()
    def test_cancel_interrupts_tls_handshake_without_sending_http_body(self):
        accepted=threading.Event();stop=threading.Event()
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(1)
                try:self.request.recv(4096);accepted.set();stop.wait(1)
                except OSError:pass
        server=socketserver.ThreadingTCPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
        event=threading.Event();timer=threading.Timer(.06,event.set);timer.start()
        try:
            started=time.monotonic()
            try:response=ConfiguredHttpTransport().send(SimpleNamespace(request_body='{"fiction":"must not send"}'),self.saved('https://127.0.0.1:'+str(server.server_address[1])+'/v1'),CancellationToken(event,time.monotonic()+.8),1000)
            except TaskCancelled:response=None
            self.assertLess(time.monotonic()-started,.3,'TLS ignored cancellation until its full timeout')
            self.assertTrue(accepted.is_set());self.assertTrue(response is None or not response.complete)
        finally:timer.cancel();timer.join();stop.set();server.shutdown();server.server_close();worker.join(2)

if __name__=='__main__':unittest.main()
