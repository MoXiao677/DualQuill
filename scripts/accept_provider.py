"""Fictional one-request acceptance CLI. Default run is a zero-network dry-run."""
import argparse
import getpass
import json
from pathlib import Path
import signal
import sys
import threading
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_writer.application.provider_acceptance import (prepare, load_plan, execute,
    confirmation_template, quality_template, record_quality, SAMPLES)
from novel_writer.storage.json_codec import strict_json_loads


def write_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def read_key():
    if not sys.stdin.isatty():
        raise ValueError('真实凭据只能在支持隐藏输入的交互终端输入')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        return getpass.getpass('本次授权请求的API Key（不保存）：')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    build = sub.add_parser('prepare', help='纯本地生成确切预览，不读取凭据或联网')
    build.add_argument('--protocol', choices=['openai-chat', 'anthropic-messages', 'gemini-content'], required=True)
    build.add_argument('--base-url', required=True)
    build.add_argument('--model', required=True)
    build.add_argument('--evidence-directory', required=True)
    build.add_argument('--budget', type=float, required=True)
    build.add_argument('--currency', required=True)
    build.add_argument('--scope', choices=['loopback', 'real-provider'], default='loopback')
    build.add_argument('--sample', choices=list(SAMPLES), default='writing')
    build.add_argument('--stream-mode', choices=['json', 'sse'], default='json')
    build.add_argument('--omit-temperature', action='store_true')
    build.add_argument('--chat-token-field', choices=['max_tokens', 'max_completion_tokens'], default='max_tokens')
    build.add_argument('--timeout-ms', type=int, default=15000)
    build.add_argument('--max-tokens', type=int, default=256)
    run = sub.add_parser('run', help='默认dry-run；--execute才消费一条明确许可')
    run.add_argument('--plan', required=True)
    run.add_argument('--confirmation')
    execution = run.add_mutually_exclusive_group()
    execution.add_argument('--execute', action='store_true')
    execution.add_argument('--dry-run', action='store_true', help='显式零外发预览（也是默认行为）')
    run.add_argument('--allow-real-provider', action='store_true', help='仅在作者另行授权后使用；不会自动读取已有凭据')
    score = sub.add_parser('record-quality', help='记录人工评分；不调用供应商或自动采纳')
    score.add_argument('--plan', required=True)
    score.add_argument('--result', required=True)
    score.add_argument('--scorecard', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            profile = {}
            if args.omit_temperature:
                profile['temperature_mode'] = 'omit'
            if args.chat_token_field != 'max_tokens':
                profile['chat_token_field'] = args.chat_token_field
            plan = prepare(protocol=args.protocol, base_url=args.base_url, model_id=args.model,
                           evidence_directory=args.evidence_directory, budget_limit=args.budget,
                           currency=args.currency, scope=args.scope, sample_id=args.sample,
                           stream_mode=args.stream_mode, profile=profile,
                           timeout_ms=args.timeout_ms, max_tokens=args.max_tokens)
            directory = Path(plan['evidence_directory'])
            directory.mkdir(parents=True, exist_ok=True)
            stem = plan['request_id']
            write_new(directory / (stem + '.preview.json'), plan)
            write_new(directory / (stem + '.confirmation.json'), confirmation_template(plan))
            write_new(directory / (stem + '.quality.json'), quality_template(plan))
            print(json.dumps(dict(dry_run=True, network_requests=0, credential_reads=0, preview=plan), ensure_ascii=False, indent=2))
            return 0
        plan = load_plan(args.plan)
        if args.action == 'record-quality':
            result = strict_json_loads(Path(args.result).read_text(encoding='utf-8'))
            scorecard = strict_json_loads(Path(args.scorecard).read_text(encoding='utf-8'))
            print(json.dumps(record_quality(plan, result, scorecard), ensure_ascii=False, indent=2))
            return 0
        if not args.execute:
            print(json.dumps(dict(dry_run=True, network_requests=0, credential_reads=0, preview=plan), ensure_ascii=False, indent=2))
            return 0
        if not args.confirmation:
            parser.error('--execute须有作者确认后的--confirmation文件')
        if plan['scope'] == 'real-provider' and not args.allow_real_provider:
            parser.error('真实供应商须另有作者授权并显式传--allow-real-provider')
        confirmation = strict_json_loads(Path(args.confirmation).read_text(encoding='utf-8'))
        event = threading.Event()
        previous = signal.signal(signal.SIGINT, lambda *_: event.set())
        try:
            supplier = read_key if plan['scope'] == 'real-provider' else (lambda: 'fictional-loopback-key')
            result = execute(plan, confirmation, supplier, event=event)
        finally:
            signal.signal(signal.SIGINT, previous)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['transport_status'] == 'passed' else 1
    except (ValueError, OSError, TypeError, KeyError):
        # Never echo user-supplied exceptions or credential input.
        print('验收预览、许可或证据路径无效；未自动重试。检查原预览与独立结果文件。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
