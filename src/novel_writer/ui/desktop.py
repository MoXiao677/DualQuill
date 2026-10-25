"""Private desktop child. stdin is both the initial secret channel and parent lifeline."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from contextlib import closing

from novel_writer.ui.server import Handler, create_server

VERSION='0.4.19'

def start_profile(profile, *, database=None, server_factory=create_server):
    """Snapshot before opening an older profile; roll back a failed initialization."""
    profile=Path(profile).resolve();profile.mkdir(parents=True,exist_ok=True)
    if database is not None and not Path(database).is_absolute():
        raise ValueError('Explicit database must be an absolute file path')
    database=Path(database or profile/'library'/'novels.sqlite3').resolve()
    marker=profile/'desktop-state.json'
    previous=json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
    if type(previous) is not dict or (previous and set(previous)!={'version'}):raise ValueError('Invalid desktop profile')
    if previous.get('version') and tuple(map(int,previous['version'].split('.')))>tuple(map(int,VERSION.split('.'))):raise ValueError('Newer desktop profile')
    snapshot=None;server=None
    if database.exists() and previous.get('version')!=VERSION:
        directory=profile/'upgrade-backups';directory.mkdir(exist_ok=True)
        snapshot=directory/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex+'.sqlite3')
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('Upgrade snapshot failed')
    try:
        server=server_factory(database,port=0,provider_path=profile/'providers.dpapi',offline=False,enable_model_generation=True,drafts_path=profile/'drafts')
        server.providers.allow_manual_configuration=True
        temporary=profile/('desktop-state-'+uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(dict(version=VERSION)),encoding='utf-8');os.replace(temporary,marker)
        return server
    except Exception:
        if server is not None:server.server_close()
        if snapshot is not None:
            with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(database)) as target:source.backup(target)
        raise


class DesktopHandler(Handler):
    def allowed_request(self, *, write=False):
        # Keep all original Host/Origin checks; additionally authenticate every read.
        return super().allowed_request(write=True)

    def do_GET(self):
        if self.path == '/api/session':
            if self.allowed_request():self.send_json(404, {'error':'Private desktop session'})
            return
        super().do_GET()

    def _handle_post(self):
        if self.path != '/api/desktop/mode':
            return super()._handle_post()
        if not self.allowed_request(write=True):return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 256 or self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                raise ValueError()
            payload=json.loads(self.rfile.read(size))
            if type(payload) is not dict or set(payload)!={'mode','confirmed'} or payload['mode'] not in ('manual','models') or payload['confirmed'] is not True:
                raise ValueError()
            enabled=payload['mode']=='models'
            for adapter in self.server.model_adapters:adapter.enabled=enabled
            self.server.book_ai.adapter.enabled=enabled
            self.server.chapter_planning.adapter.enabled=enabled
            self.server.model_planning.adapter.enabled=enabled
            self.server.scene_expansion.adapter.enabled=enabled
            self.server.rule_reviews.adapter.enabled=enabled
            self.server.styles.adapter.enabled=enabled
            self.server.public_search.adapter.enabled=enabled
            self.server.style_trials.adapter.enabled=enabled
            self.server.providers.offline=not enabled
            self.server.offline=not enabled
            self.server.model_generation_enabled=enabled
            if not enabled:
                # Do not release reservations or silently restart interrupted model work.
                with self.server.task_coordinator.lock:
                    active=list(self.server.task_coordinator.active.values())
                for _,token in active:token.event.set()
            self.send_json(200,dict(mode=payload['mode'],real_model_enabled=enabled,
                note='Each remote request still requires its own frozen-content and cost confirmation.'))
        except (ValueError,TypeError,UnicodeError):
            self.send_json(422,{'error':'请选择手动或模型模式，并明确确认本次会话；仍须逐请求确认外发内容与费用。'})


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--database',type=Path)
    args=parser.parse_args(argv)
    profile=args.profile.resolve()
    server=None
    try:
        line=sys.stdin.readline(1025)
        hello=json.loads(line)
        if type(hello) is not dict or set(hello)!={'token','nonce'} or any(type(hello[k]) is not str or not re.fullmatch('[a-f0-9]{64}',hello[k]) for k in hello):
            raise ValueError('Invalid parent handshake')
        profile.mkdir(parents=True,exist_ok=True)
        temporary=profile/'tmp';temporary.mkdir(exist_ok=True)
        os.environ['TEMP']=os.environ['TMP']=str(temporary);tempfile.tempdir=str(temporary)
        server=start_profile(profile,database=args.database)
        server.RequestHandlerClass=DesktopHandler
        server.token=hello['token']
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True)
        worker.start()
        print(json.dumps(dict(type='ready',protocol=1,port=server.server_address[1],pid=os.getpid(),nonce=hello['nonce'])),flush=True)
        # Parent death closes stdin, including a main-process crash or forced termination.
        # No command interpreter or dynamic imports are exposed here.
        while sys.stdin.read(1):pass
        server.shutdown();worker.join(3)
        return 0
    except (ValueError,OSError,RuntimeError):
        print(json.dumps(dict(type='error',code='desktop_start_failed')),flush=True)
        return 1
    finally:
        if server is not None:server.server_close()


if __name__=='__main__':raise SystemExit(main())
