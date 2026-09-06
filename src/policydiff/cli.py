"""Offline commands. Exit zero means a report was produced, never a robot pass."""
import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .demo import fixture
from .engine import compare
from .io import csv_bytes, load_inputs, parse_csv, parse_manifest, sha256
from .report import markdown
from .schema import EvidenceError


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def write_bundle(output, report, snapshots):
    """Exclusive creation; COMPLETE.json is written last. Partial writes stay visible."""
    output = Path(output)
    payloads = dict(snapshots, **{'report.json': encode(report), 'report.md': markdown(report).encode('utf-8')})
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        with (output / name).open('xb') as handle:
            handle.write(data)
    receipt = {'status': 'complete', 'producer': 'policydiff', 'version': __version__,
               'evidence_origin': report['evidence_origin'],
               'required_coverage_complete': report['required_coverage_complete'],
               'eligible_slice_count': report['eligible_slice_count'],
               'observed_totals': report['observed_totals'],
               'declared_family_size': report['declared_family_size'],
               'input_sha256': report.get('inputs'),
               'sha256': {name: sha256(data) for name, data in payloads.items()}}
    with (output / 'COMPLETE.json').open('xb') as handle:
        handle.write(encode(receipt))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('compare', 'validate'):
        command = sub.add_parser(name)
        command.add_argument('--manifest', required=True, type=Path)
        command.add_argument('--episodes', required=True, type=Path)
        command.add_argument('--strict-coverage', action='store_true', help='exit 3 if any required slice lacks outcomes in any declared arm (including retest if declared)')
        if name == 'compare':
            command.add_argument('--output', type=Path, help='new directory; omitted writes report JSON to stdout')
    demo = sub.add_parser('demo', help='generate explicitly synthetic inputs and a report')
    demo.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            manifest, rows = fixture()
            snapshots = {'manifest.input.json': encode(manifest), 'episodes.input.csv': csv_bytes(rows)}
            manifest, rows = parse_manifest(snapshots['manifest.input.json']), parse_csv(snapshots['episodes.input.csv'])
            inputs = {'manifest_sha256': sha256(snapshots['manifest.input.json']),
                      'episodes_sha256': sha256(snapshots['episodes.input.csv'])}
        else:
            manifest, rows, inputs, snapshots = load_inputs(args.manifest, args.episodes)
        report = compare(manifest, rows)
        report['inputs'] = inputs
        report['producer'] = {'name': 'policydiff', 'version': __version__}
        if args.command == 'validate':
            print(json.dumps({key: report[key] for key in ('input_valid', 'evidence_origin', 'required_coverage_complete', 'coverage_counts')}))
        elif args.output:
            write_bundle(args.output, report, snapshots)
            print(json.dumps(dict({key: report[key] for key in (
                'status', 'required_coverage_complete', 'evidence_origin', 'coverage_counts',
                'observed_totals', 'eligible_slice_count', 'has_inferential_regression')}, output=str(args.output.resolve()))))
        else:
            sys.stdout.write(encode(report).decode())
        return 3 if getattr(args, 'strict_coverage', False) and not report['required_coverage_complete'] else 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({'status': 'invalid_input_or_output', 'error': str(exc)[:1000]}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({'status': 'internal_error', 'error': f'{type(exc).__name__}: {exc}'[:1000]}), file=sys.stderr)
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
