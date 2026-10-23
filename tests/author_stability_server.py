"""Owned local UI fixture. Faults affect only this process and its explicit root."""
import errno
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

from novel_writer.ui.server import create_server


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    drafts = root / 'drafts'
    server = create_server(root / 'fiction.sqlite3', port=0, offline=True,
                           provider_path=root / 'never-configured.dpapi', drafts_path=drafts)
    original_replace = __import__('os').replace
    original_iterdir, original_unlink = Path.iterdir, Path.unlink
    original_execute = server.service.execute

    def replace(source, target, *args, **kwargs):
        if Path(target).parent == drafts and (root / 'fault-draft-write').exists():
            raise OSError(errno.ENOSPC, 'fictional scoped full disk')
        return original_replace(source, target, *args, **kwargs)

    def iterdir(path):
        if path == drafts and (root / 'fault-draft-read').exists():
            raise PermissionError('fictional scoped denied directory')
        return original_iterdir(path)

    def unlink(path, *args, **kwargs):
        if path.parent == drafts and path.suffix == '.json' and (root / 'fault-draft-clear').exists():
            raise PermissionError('fictional scoped denied clear')
        return original_unlink(path, *args, **kwargs)

    def execute(project, action, fields, **kwargs):
        if action == 'save_chapter' and (root / 'fault-body-save').exists():
            raise sqlite3.OperationalError('fictional scoped database full')
        return original_execute(project, action, fields, **kwargs)

    with patch('os.replace', replace), patch.object(Path, 'iterdir', iterdir), patch.object(Path, 'unlink', unlink), patch.object(server.service, 'execute', execute):
        print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}')), flush=True)
        try:
            server.serve_forever(poll_interval=.05)
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
