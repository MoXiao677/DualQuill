"""离线完整备份工具；不启动服务、不读取密钥、不覆盖既有目标。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main(argv=None):
    from novel_writer.application.backups import BackupError, create_backup, preflight_backup, restore_backup
    from novel_writer.application.backup_staging import (
        StagingError, inspect_staging, cleanup_staging, inspect_staging_recovery, recover_staging)
    parser = argparse.ArgumentParser(description='Novel Writer完整库V1备份/预检/新目录恢复')
    commands = parser.add_subparsers(dest='command', required=True)
    backup = commands.add_parser('backup')
    backup.add_argument('--database', type=Path, required=True)
    backup.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--input', type=Path, required=True)
    restore = commands.add_parser('restore')
    restore.add_argument('--input', type=Path, required=True)
    restore.add_argument('--target', type=Path, required=True, help='尚不存在的新目录；父目录必须存在')
    inspect = commands.add_parser('inspect-staging', help='仅读明确暂存目录的归属和OS活动锁')
    inspect.add_argument('--directory', type=Path, required=True)
    cleanup = commands.add_parser('cleanup-staging', help='只清理明确目录及匹配编号的非活动暂存')
    cleanup.add_argument('--directory', type=Path, required=True)
    cleanup.add_argument('--operation-id', required=True)
    for name, help_text in (('inspect-staging-recovery', '只核对明确原目录/恢复目录及操作编号'),
                            ('recover-staging', '按创建时可信归属显式归还元数据或完成元数据清理')):
        recovery = commands.add_parser(name, help=help_text)
        recovery.add_argument('--directory', type=Path, required=True)
        recovery.add_argument('--recovery-directory', type=Path, required=True)
        recovery.add_argument('--operation-id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'backup':
            manifest = create_backup(args.database, args.output)
            result = {'backup_path': str(args.output.resolve()), 'counts': manifest['counts'], 'verified': True,
                      'cleanup_warnings':getattr(manifest,'cleanup_warnings',[])}
        elif args.command == 'verify':
            result = preflight_backup(args.input)
            result = {'counts': result['counts'], 'verified': True}
        elif args.command == 'restore':
            result = restore_backup(args.input, args.target)
            result = {key: result[key] for key in ('database_path','counts','verified','credentials_restored','cleanup_warnings')}
        elif args.command == 'inspect-staging':
            result = inspect_staging(args.directory)
        elif args.command == 'cleanup-staging':
            result = cleanup_staging(args.directory, args.operation_id)
        elif args.command == 'inspect-staging-recovery':
            result = inspect_staging_recovery(args.directory, args.recovery_directory, args.operation_id)
        else:
            result = recover_staging(args.directory, args.recovery_directory, args.operation_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BackupError, StagingError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('操作取消；已有数据保留。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
