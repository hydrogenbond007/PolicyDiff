"""Offline commands. Exit zero means the command succeeded, never a policy pass."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__
from .bundle import verify_bundle, write_bundle
from .contract import MAX_SNAPSHOT_BYTES, describe_contract_change
from .demo import fixture
from .engine import compare
from .io import csv_bytes, encode, load_inputs, parse_csv, parse_json, parse_manifest, read_snapshot, sha256
from .schema import EvidenceError, validate_manifest, validate_rows
from .triage import TRANSITIONS, select_cases


def _discard_broken_pipe(stream):
    # Avoid a second shutdown flush changing the documented exit to Python's 120.
    try:
        with open(os.devnull, 'wb') as sink:
            os.dup2(sink.fileno(), stream.fileno())
    except (OSError, ValueError):
        pass


def _emit_error(error):
    try:
        print(json.dumps(error), file=sys.stderr, flush=True)
    except BrokenPipeError:
        _discard_broken_pipe(sys.stderr)
    except (OSError, ValueError):
        pass  # The exit code remains meaningful when diagnostics cannot be delivered.


def _error_limit(value):
    try:
        number = int(value)
    except ValueError:
        number = 0
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError('must be an integer from 1 to 100')
    return number


def _contract_input(path, side):
    try:
        data = read_snapshot(path, maximum=MAX_SNAPSHOT_BYTES)
        return parse_json(data, 'contract snapshot'), sha256(data)
    except (EvidenceError, OSError) as exc:
        raise EvidenceError(f'{side} snapshot: {exc}', details={'snapshot_side': side}) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('compare', 'validate', 'cases'):
        command = sub.add_parser(name)
        command.add_argument('--manifest', required=True, type=Path)
        command.add_argument('--episodes', required=True, type=Path)
        command.add_argument('--strict-coverage', action='store_true', help='exit 3 if any required slice lacks outcomes in any declared arm (including retest if declared)')
        if name == 'compare':
            command.add_argument('--output', type=Path, help='new directory; omitted writes report JSON to stdout')
        elif name == 'validate':
            command.add_argument('--max-errors', type=_error_limit, default=20,
                                 help='maximum diagnostics displayed (1–100); all records are checked')
        else:
            command.add_argument('--slice', dest='slice_ids', action='append', help='display this declared slice; repeatable')
            command.add_argument('--transition', choices=TRANSITIONS, action='append',
                                 help='display this transition; repeatable; default lost, gained, unresolved')
            command.add_argument('--limit', type=int, default=100, help='maximum displayed cases (1–10000); default 100')
    demo = sub.add_parser('demo', help='generate explicitly synthetic inputs and a report')
    demo.add_argument('--output', required=True, type=Path)
    verify = sub.add_parser('verify', help='check a saved bundle; not a policy pass or authenticity check')
    verify.add_argument('--bundle', required=True, type=Path)
    contract = sub.add_parser('inspect-contract', help='describe recorded protocol differences; not a comparability check')
    contract.add_argument('--before', required=True, type=Path)
    contract.add_argument('--after', required=True, type=Path)
    args = parser.parse_args(argv)
    completed_result = {}
    record_lines = []
    try:
        if args.command == 'inspect-contract':
            before, before_hash = _contract_input(args.before, 'before')
            after, after_hash = _contract_input(args.after, 'after')
            result = describe_contract_change(before, after)
            result['inputs'] = {'before_snapshot_sha256': before_hash, 'after_snapshot_sha256': after_hash}
            completed_result = {'command': args.command, 'result_status': result['status']}
            sys.stdout.write(encode(result).decode())
            sys.stdout.flush()
            return 0
        if args.command == 'verify':
            result = verify_bundle(args.bundle)
            completed_result = {'command': 'verify', 'result_status': result['status']}
            print(json.dumps(result), flush=True)
            return 0
        if args.command == 'demo':
            manifest, rows = fixture()
            snapshots = {'manifest.input.json': encode(manifest), 'episodes.input.csv': csv_bytes(rows)}
            manifest, rows = parse_manifest(snapshots['manifest.input.json']), parse_csv(snapshots['episodes.input.csv'])
            inputs = {'manifest_sha256': sha256(snapshots['manifest.input.json']),
                      'episodes_sha256': sha256(snapshots['episodes.input.csv'])}
        else:
            manifest, rows, inputs, snapshots = load_inputs(args.manifest, args.episodes, record_lines=record_lines)
        if args.command == 'validate':
            validate_manifest(manifest)
            validate_rows(manifest, rows, max_errors=args.max_errors)
        report = compare(manifest, rows)
        report['inputs'] = inputs
        if args.command == 'cases':
            result = select_cases(report, slice_ids=args.slice_ids, transitions=args.transition, limit=args.limit)
            completed_result = {'command': 'cases', 'result_status': 'cases_selected'}
            sys.stdout.write(encode(result).decode())
        elif args.command == 'validate':
            completed_result = {'command': 'validate', 'result_status': 'inputs_validated'}
            print(json.dumps({key: report[key] for key in ('input_valid', 'evidence_origin', 'required_coverage_complete', 'coverage_counts')}))
        elif args.output:
            output_path = str(args.output.resolve())
            write_bundle(args.output, report, snapshots)
            completed_result = {'command': args.command, 'result_status': 'report_created',
                                'bundle_status': 'complete', 'output': output_path}
            print(json.dumps(dict({key: report[key] for key in (
                'status', 'required_coverage_complete', 'evidence_origin', 'coverage_counts',
                'observed_totals', 'eligible_slice_count', 'has_inferential_regression')}, output=output_path)))
        else:
            completed_result = {'command': 'compare', 'result_status': 'report_created'}
            sys.stdout.write(encode(report).decode())
        sys.stdout.flush()
        return 3 if getattr(args, 'strict_coverage', False) and not report['required_coverage_complete'] else 0
    except (EvidenceError, OSError) as exc:
        if isinstance(exc, BrokenPipeError):
            _discard_broken_pipe(sys.stdout)
        error = {'status': 'invalid_input_or_output', 'error': str(exc)[:1000]}
        if isinstance(exc, EvidenceError):
            error.update(exc.details)
            for item in error.get('errors', [error]):
                index = item.get('record', 0)
                if 0 < index <= len(record_lines):
                    item['csv_line_end'] = record_lines[index - 1]
        if completed_result:
            error.update(status='output_notification_failed', **completed_result)
        _emit_error(error)
        return 2
    except Exception as exc:
        _emit_error({'status': 'internal_error', 'error': f'{type(exc).__name__}: {exc}'[:1000], **completed_result})
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
