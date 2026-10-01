#!/usr/bin/env python3
"""Portable, offline packaging checks; build tools must already be installed."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

PACKAGE = Path(__file__).resolve().parents[1]
REQUIRED_TOP = ('pyproject.toml', 'MANIFEST.in', 'README.md', 'SCHEMA.md', 'ARCHITECTURE.md',
                'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'REVIEW_NOTES.md',
                'RELEASE_REVIEW.md', 'THIRD_PARTY_NOTICES.md', 'EXECUTION.md', '.gitignore', '.gitattributes')
SOURCE_TREES = {'src/policydiff': '.py', 'tests': '.py', 'scripts': '.py', '.github/workflows': '.yml'}
# These generated/local-only root directories are excluded, not verified. Do not
# extend this into a general ignore-glob parser that could hide source assets.
EXCLUDED_ROOT_DIRS = {'.git', 'build', 'dist', '.venv', 'demo-output', 'another-new-report',
                      'release-check', '.pytest_cache', 'htmlcov', 'private-data'}
EXCLUDED_ROOT_FILES = {'PKG-INFO', '.coverage'}
COMMAND_TIMEOUT = 120


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_inventory(package, output):
    """Reject source files the clean-copy recipe cannot represent; never use Git."""
    package, output = Path(package), Path(output).resolve()
    if package.is_symlink():
        raise RuntimeError('symlink source directory is not release-safe')
    package = package.resolve()
    sources = []

    def visit(directory):
        for path in sorted(directory.iterdir()):
            name = path.relative_to(package).as_posix()
            if path == output:
                continue
            if (path.parent == package and path.name in EXCLUDED_ROOT_FILES
                    and path.is_file() and not path.is_symlink()):
                continue
            excluded_dir = (path.parent == package and path.name in EXCLUDED_ROOT_DIRS
                            or path.name == '__pycache__' or path.name.endswith('.egg-info'))
            if excluded_dir and path.is_dir():
                continue
            if path.is_symlink():
                raise RuntimeError(f'symlink source is not release-safe: {name}')
            if path.is_dir():
                visit(path)
            elif path.is_file():
                supported = name in (*REQUIRED_TOP, 'LICENSE') or any(
                    name.startswith(tree + '/') and path.suffix == suffix
                    for tree, suffix in SOURCE_TREES.items())
                if not supported:
                    raise RuntimeError(f'unsupported release source file: {name}')
                sources.append(path)
            else:
                raise RuntimeError(f'non-regular release source file: {name}')

    visit(package)
    missing = set(REQUIRED_TOP) - {path.relative_to(package).as_posix() for path in sources}
    if missing:
        raise RuntimeError(f'required release file missing: {sorted(missing)[0]}')
    return sorted(sources)


def run_logged(label, command, *, cwd, output, env, commands, expected=0):
    """Preserve partial diagnostics even when a bounded child command times out."""
    timed_out = None
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True,
                                timeout=COMMAND_TIMEOUT)
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = exc
        stdout, stderr, code = exc.stdout or '', exc.stderr or '', None
    stdout = stdout.decode('utf-8', errors='replace') if isinstance(stdout, bytes) else stdout
    stderr = stderr.decode('utf-8', errors='replace') if isinstance(stderr, bytes) else stderr
    (output / (label + '.stdout.txt')).write_text(stdout, encoding='utf-8')
    (output / (label + '.stderr.txt')).write_text(stderr, encoding='utf-8')
    record = {'label': label, 'exit_code': code, 'expected': expected}
    if timed_out is not None:
        record.update(timed_out=True, timeout_seconds=timed_out.timeout)
    commands.append(record)
    if timed_out is not None or code != expected:
        diagnostics = json.dumps({'stdout_tail': stdout[-4000:], 'stderr_tail': stderr[-4000:]})
        print(f'{label} failure diagnostics: {diagnostics}', file=sys.stderr)
        reason = f'timed out after {timed_out.timeout}s' if timed_out is not None else f'exit {code}, expected {expected}'
        raise RuntimeError(f'{label}: {reason}; see saved logs and printed diagnostics') from timed_out
    return result


def verify_sdist_sources(archive, source_hashes):
    """Check every inventoried source, not one legacy test-file sentinel."""
    names = archive.getnames()
    roots = {name.split('/', 1)[0] for name in names}
    if len(roots) != 1 or len(names) != len(set(names)):
        raise RuntimeError('source distribution must have one root and unique member names')
    root = next(iter(roots))
    for name, expected in source_hashes.items():
        try:
            member = archive.getmember(root + '/' + name)
        except KeyError as exc:
            raise RuntimeError(f'source distribution omitted source: {name}') from exc
        if not member.isfile():
            raise RuntimeError(f'non-regular source distribution member: {name}')
        with archive.extractfile(member) as handle:
            if hashlib.sha256(handle.read()).hexdigest() != expected:
                raise RuntimeError(f'source distribution changed source: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new directory; never overwritten')
    args = parser.parse_args()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(f'Cannot create new check directory: {exc}', file=sys.stderr)
        return 2
    out = args.output.resolve()
    receipt = {'status': 'started', 'python': sys.version, 'commands': [],
               'started_utc': datetime.now(timezone.utc).isoformat(), 'new_policy_episodes': 0}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
               PIP_NO_CACHE_DIR='1')
    env.pop('PYTHONPATH', None)

    def run(label, command, cwd=out, expected=0):
        return run_logged(label, command, cwd=cwd, output=out, env=env,
                          commands=receipt['commands'], expected=expected)

    try:
        # Build from a clean allowlisted copy, never from ignored local outputs.
        clean = out / 'clean-source'
        clean.mkdir()
        sources = source_inventory(PACKAGE, out)
        source_hashes = {}
        for source in sources:
            name = source.relative_to(PACKAGE).as_posix()
            dest = clean / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            source_hashes[name] = sha(dest)
        receipt['source_sha256'] = source_hashes
        run('build-sdist', [sys.executable, '-c', "from setuptools.build_meta import build_sdist; build_sdist('dist')"], clean)
        sdists = list((clean / 'dist').glob('*.tar.gz'))
        if len(sdists) != 1:
            raise RuntimeError('expected one source distribution')
        with tarfile.open(sdists[0]) as archive:
            names = archive.getnames()
            verify_sdist_sources(archive, source_hashes)
            receipt['sdist_source_hashes_checked'] = True
            receipt['sdist_contents'] = names
        run('wheel-from-sdist', [sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-deps',
                                '--no-build-isolation', '--wheel-dir', str(out / 'wheel'), str(sdists[0])])
        wheels = list((out / 'wheel').glob('*.whl'))
        if len(wheels) != 1:
            raise RuntimeError('expected one wheel')
        with zipfile.ZipFile(wheels[0]) as archive:
            names = archive.namelist()
            if any(not (n.startswith('policydiff/') or n.startswith('policydiff-')) for n in names):
                raise RuntimeError('unexpected top-level wheel content')
            if any(n.endswith(('.pt', '.pth', '.npz', '.mp4', '.pem', '.key')) for n in names):
                raise RuntimeError('private/binary artifact in wheel')
            receipt['wheel_contents'] = names
        receipt.update(sdist_sha256=sha(sdists[0]), wheel_sha256=sha(wheels[0]))
        run('create-venv', [sys.executable, '-m', 'venv', str(out / 'venv')])
        python = str(out / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
        run('offline-install', [python, '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheels[0])])
        installed_runner = '''import pathlib, sys, sysconfig, unittest
import policydiff
site = pathlib.Path(sysconfig.get_paths()['purelib']).resolve()
def assert_installed():
    for name, module in list(sys.modules.items()):
        if name == 'policydiff' or name.startswith('policydiff.'):
            path = pathlib.Path(module.__file__).resolve()
            if not path.is_relative_to(site):
                raise RuntimeError('Tests imported source instead of installed package: ' + str(path))
assert_installed()
suite = unittest.defaultTestLoader.discover(sys.argv[1])
assert_installed()
if suite.countTestCases() == 0:
    raise RuntimeError('No installed-package tests were collected')
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert_installed()
print('Installed package path verified: ' + str(pathlib.Path(policydiff.__file__).resolve()))
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
        run('installed-tests', [python, '-B', '-c', installed_runner, str(clean / 'tests')])
        cli = [python, '-B', '-m', 'policydiff']
        version = run('installed-version', cli + ['--version']).stdout.strip()
        console = str(out / 'venv' / ('Scripts/policydiff.exe' if os.name == 'nt' else 'bin/policydiff'))
        console_version = run('installed-console-version', [console, '--version']).stdout.strip()
        if console_version != version:
            raise RuntimeError('console-script and module entry points disagree')
        metadata = run('installed-metadata-version', [python, '-c',
                       "from importlib.metadata import version; print(version('policydiff'))"]).stdout.strip()
        if version != metadata:
            raise RuntimeError('runtime and installed metadata versions differ')
        run('installed-demo', cli + ['demo', '--output', str(out / 'demo')])
        inputs = ['--manifest', str(out / 'demo/manifest.input.json'), '--episodes', str(out / 'demo/episodes.input.csv')]
        run('installed-validate', cli + ['validate'] + inputs)
        run('installed-console-validate', [console, 'validate'] + inputs)
        run('installed-compare', cli + ['compare'] + inputs + ['--output', str(out / 'comparison')])
        run('installed-verify', cli + ['verify', '--bundle', str(out / 'demo')])
        run('installed-console-verify', [console, 'verify', '--bundle', str(out / 'comparison')])
        view_args = ['cases'] + inputs + ['--slice', 'old-camera', '--transition', 'lost', '--limit', '2']
        view = json.loads(run('installed-cases', cli + view_args).stdout)
        console_view = json.loads(run('installed-console-cases', [console] + view_args).stdout)
        if view != console_view or view['selection']['shown_cases'] != 2 or not view['selection']['truncated']:
            raise RuntimeError('installed case-selection entry points disagree or hide truncation')
        if len(view['slices']) != 6 or view['comparison']['observed_totals']['declared_pairs'] != 72:
            raise RuntimeError('case selection changed the full comparison population')
        run('case-view-strict-missingness', cli + view_args + ['--strict-coverage'], expected=3)
        run('installed-cases-unknown-slice', cli + ['cases'] + inputs + ['--slice', 'nope'], expected=2)
        run('installed-cases-invalid-limit', cli + ['cases'] + inputs + ['--limit', '0'], expected=2)
        group_args = ['triage'] + inputs + ['--group-by', 'axis', '--rank-by', 'unresolved']
        grouped = json.loads(run('installed-triage', cli + group_args).stdout)
        console_grouped = json.loads(run('installed-console-triage', [console] + group_args).stdout)
        if grouped != console_grouped or grouped['status'] != 'changes_grouped':
            raise RuntimeError('installed grouped-triage entry points disagree')
        if sum(group['declared_pairs'] for group in grouped['groups']) != 72:
            raise RuntimeError('grouping changed the full declared population')
        if grouped['groups'][0]['dimensions'] != {'axis': 'dynamics'}:
            raise RuntimeError('missing-evidence ranking hid the untested group')
        rendered = run('installed-triage-markdown', cli + group_args + ['--format', 'markdown']).stdout
        if 'Unresolved evidence' not in rendered or 'not measured (0/12 pairs)' not in rendered:
            raise RuntimeError('grouped Markdown hid missing or unmeasured evidence')
        run('triage-strict-missingness', cli + group_args + ['--strict-coverage'], expected=3)
        run('installed-triage-invalid-group', cli + ['triage'] + inputs + ['--group-by', 'typo'], expected=2)
        demo_rows = list(csv.DictReader(io.StringIO((out / 'demo/episodes.input.csv').read_text(encoding='utf-8'))))
        for row in demo_rows[:2]:
            row['success'] = 'invalid'
        bad_csv = out / 'invalid-episodes.csv'
        with bad_csv.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=demo_rows[0].keys())
            writer.writeheader()
            writer.writerows(demo_rows)
        diagnostic_args = ['validate', '--manifest', str(out / 'demo/manifest.input.json'),
                           '--episodes', str(bad_csv), '--max-errors', '1']
        diagnostics = json.loads(run('installed-diagnostics', cli + diagnostic_args, expected=2).stderr)
        console_diagnostics = json.loads(run('installed-console-diagnostics', [console] + diagnostic_args, expected=2).stderr)
        if diagnostics != console_diagnostics or diagnostics['error_count'] != 2 or not diagnostics['errors_truncated']:
            raise RuntimeError('installed diagnostics disagree or lose errors')
        # Independent synthetic protocol descriptions never enter the outcome bundle.
        description = {'contract_snapshot_schema_version': 1, 'label': 'Synthetic before',
                       'declared_for_contract_sha256': 'a' * 64,
                       'fields': {'budget.wall_seconds': {'status': 'recorded', 'value': '600'},
                                  'success_rule': {'status': 'unrecorded', 'value': None}}}
        before, after = out / 'before.json', out / 'after.json'
        before.write_text(json.dumps(description), encoding='utf-8')
        description['fields']['budget.wall_seconds']['value'] = '3600'
        description['label'] = 'Synthetic after'
        after.write_text(json.dumps(description), encoding='utf-8')
        contract_args = ['inspect-contract', '--before', str(before), '--after', str(after)]
        contract = json.loads(run('installed-contract', cli + contract_args).stdout)
        console_contract = json.loads(run('installed-console-contract', [console] + contract_args).stdout)
        if (contract != console_contract or contract['counts'] != {'same': 0, 'changed': 1, 'undetermined': 1}
                or not contract['same_declared_digest_with_field_changes']
                or contract['snapshots']['before']['label'] != 'Synthetic before'
                or contract['snapshots']['after']['label'] != 'Synthetic after'
                or contract['inputs'] != {'before_snapshot_sha256': sha(before), 'after_snapshot_sha256': sha(after)}):
            raise RuntimeError('installed contract description disagrees or loses changes/unknowns/source hashes')
        after.write_text('{}', encoding='utf-8')
        run('installed-contract-invalid-input', cli + contract_args, expected=2)
        # External-runner inventory is descriptive and does not enter comparisons.
        external = {'version': 1, 'status': 'success', 'eval': {'task': 'synthetic'},
                    'results': {'total_scenes': 1, 'total_trials': 2, 'errored_trials': 1},
                    'samples': [{'scene_id': 's0', 'status': 'success',
                                 'epochs': [{'operator': 0.0}, {}],
                                 'operator_judgements': [None, None]}]}
        log_path = out / 'external-log.json'
        log_path.write_text(json.dumps(external), encoding='utf-8')
        inspect_args = ['inspect-log', '--format', 'inspect-robots', '--input', str(log_path)]
        inventory = json.loads(run('installed-log-inventory', cli + inspect_args).stdout)
        console_inventory = json.loads(run('installed-console-log-inventory', [console] + inspect_args).stdout)
        if (inventory != console_inventory or inventory['comparison_support'] != 'not_established'
                or inventory['observed_counts'] != {'scenes': 1, 'epoch_records': 2,
                    'scored_epoch_records': 1, 'empty_epoch_records': 1,
                    'operator_scores_without_recorded_judgement': 1}
                or inventory['scorers'] != [{'name': 'operator', 'scored_epoch_records': 1,
                                             'epochs_without_score': 1}]
                or inventory['inputs'] != {'log_sha256': sha(log_path)}):
            raise RuntimeError('installed external-log inventory disagrees or loses accounting/source hash')
        log_path.write_text('{"version":2}', encoding='utf-8')
        run('installed-log-invalid-version', cli + inspect_args, expected=2)
        catalogue = json.loads(run('installed-catalogue', cli + ['catalog', '--suite', 'libero_object']).stdout)
        console_catalogue = json.loads(run('installed-console-catalogue', [console, 'catalog', '--suite', 'libero_object']).stdout)
        if (catalogue != console_catalogue or catalogue['catalogue_task_count'] != 130
                or catalogue['selected_task_count'] != 10
                or any(task['availability'] != 'listed' for task in catalogue['tasks'])):
            raise RuntimeError('installed catalogue disagrees or fabricates readiness')
        run('installed-catalogue-invalid-suite', cli + ['catalog', '--suite', 'nope'], expected=2)
        evaluation_path = out / 'not-an-evaluation.json'
        evaluation_path.write_text('{}', encoding='utf-8')
        evaluation_args = ['evaluate', '--config', str(evaluation_path), '--output', str(out / 'never-executed')]
        run('installed-evaluate-needs-trust', cli + evaluation_args, expected=2)
        run('installed-evaluate-invalid-config', cli + evaluation_args + ['--allow-local-code'], expected=2)
        if (out / 'never-executed').exists():
            raise RuntimeError('invalid evaluation created an execution directory')
        run('strict-missingness', cli + ['validate'] + inputs + ['--strict-coverage'], expected=3)
        run('refuse-overwrite', cli + ['demo', '--output', str(out / 'demo')], expected=2)
        for path in (out / 'demo').iterdir():
            if path.read_bytes() != (out / 'comparison' / path.name).read_bytes():
                raise RuntimeError('same-input bundles differ')
        for name in ('demo', 'comparison'):
            marker = json.loads((out / name / 'COMPLETE.json').read_text(encoding='utf-8'))
            if marker['evidence_origin'] != 'synthetic' or marker['eligible_slice_count'] != 0:
                raise RuntimeError('synthetic inference boundary failed')
            for filename, expected_hash in marker['sha256'].items():
                if sha(out / name / filename) != expected_hash:
                    raise RuntimeError('bundle hash mismatch')
        final_hashes = {path.relative_to(PACKAGE).as_posix(): sha(path) for path in source_inventory(PACKAGE, out)}
        if final_hashes != source_hashes:
            raise RuntimeError('source changed during checks')
        receipt.update(status='verified', source_unchanged=True, deterministic_bundles=True,
                       bundle_hashes_verified=True, finished_utc=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'receipt': str(out / 'receipt.json'), 'error': receipt.get('error')}))
    return 0 if receipt['status'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
