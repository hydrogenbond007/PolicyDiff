#!/usr/bin/env python3
"""Portable, offline packaging checks; build tools must already be installed."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

PACKAGE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        p = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=120)
        (out / (label + '.stdout.txt')).write_text(p.stdout, encoding='utf-8')
        (out / (label + '.stderr.txt')).write_text(p.stderr, encoding='utf-8')
        receipt['commands'].append({'label': label, 'exit_code': p.returncode, 'expected': expected})
        if p.returncode != expected:
            diagnostics = json.dumps({'stdout_tail': p.stdout[-4000:], 'stderr_tail': p.stderr[-4000:]})
            print(f'{label} failure diagnostics: {diagnostics}', file=sys.stderr)
            raise RuntimeError(f'{label}: exit {p.returncode}, expected {expected}; see saved logs and printed diagnostics')
        return p

    try:
        # Build from a clean allowlisted copy, never from ignored local outputs.
        clean = out / 'clean-source'
        clean.mkdir()
        top = ('pyproject.toml', 'MANIFEST.in', 'README.md', 'SCHEMA.md', 'ARCHITECTURE.md',
               'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'REVIEW_NOTES.md', 'RELEASE_REVIEW.md', '.gitignore', '.gitattributes')
        sources = [PACKAGE / p for p in top]
        for directory, suffix in (('src/policydiff', '.py'), ('tests', '.py'), ('scripts', '.py'), ('.github/workflows', '.yml')):
            sources.extend(p for p in (PACKAGE / directory).rglob('*') if p.is_file() and p.suffix == suffix)
        if (PACKAGE / 'LICENSE').is_file():
            sources.append(PACKAGE / 'LICENSE')
        source_hashes = {}
        for source in sorted(sources):
            if not source.is_file():
                raise RuntimeError(f'required release file missing: {source.relative_to(PACKAGE)}')
            if source.is_symlink():
                raise RuntimeError('symlink source is not release-safe')
            name = str(source.relative_to(PACKAGE))
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
            if not any(n.endswith('/tests/test_contract.py') for n in names):
                raise RuntimeError('source distribution omitted tests')
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
        if any(sha(PACKAGE / name) != expected_hash for name, expected_hash in source_hashes.items()):
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
