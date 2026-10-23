"""Synthetic browser fixture; receives only its own native test database path."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from novel_writer.ui.server import create_server
parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--target',type=Path,required=True);args=parser.parse_args()
args.target.mkdir(parents=True,exist_ok=False);database=args.target/'browser-fiction.sqlite3'
with closing(sqlite3.connect(args.source.resolve().as_uri()+'?mode=ro',uri=True)) as original,closing(sqlite3.connect(database)) as clone:original.backup(clone)
server=create_server(database,port=0,provider_path=args.target/'browser-fictitious.dpapi')
try:
 print('http://127.0.0.1:'+str(server.server_port),flush=True);server.serve_forever(poll_interval=.05)
finally:server.server_close()
