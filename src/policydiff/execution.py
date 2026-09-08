"""Opt-in local LIBERO execution; separate from the pure comparison engine."""
import hashlib
import importlib.metadata
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .bundle import write_bundle
from .catalogue import LIBERO_COMMIT, resolve_task
from .engine import compare
from .io import csv_bytes, encode, parse_json, read_snapshot, sha256
from .schema import COLUMNS, ROLES, EvidenceError, fields, integer, require, text, validate_manifest, validate_rows

ABI = 'libero-panda-rgb128-proprio-osc7-v1'
MAX_TRIALS = 300


def runner_hashes():
    return {path.name: file_hash(path) for path in sorted(Path(__file__).parent.glob('*.py'))}


def runtime_versions():
    try:
        return {name: importlib.metadata.version(name) for name in ('numpy', 'torch', 'robosuite', 'mujoco')}
    except importlib.metadata.PackageNotFoundError as exc:
        raise EvidenceError('activate a compatible LIBERO environment before planning or evaluating') from exc


def file_hash(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'execution inputs must be regular non-symlink files')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare_evaluation(config, *, base_dir):
    """Validate an explicit run request and freeze inputs; no imports or episodes."""
    config = deepcopy(config)
    fields(config, ('evaluation_schema_version', 'title', 'libero_root', 'adapter', 'family',
                    'baseline', 'candidate', 'change', 'retest', 'seed', 'timeout_seconds', 'tasks'),
           label='evaluation')
    require(type(config['evaluation_schema_version']) is int and config['evaluation_schema_version'] == 1,
            'unsupported evaluation schema version')
    require(os.name == 'posix', 'experimental evaluation currently requires POSIX process isolation')
    text(config['title'], 'title')
    text(config['family'], 'family')
    require(isinstance(config['change'], dict), 'change must be an object')
    require(type(config['retest']) is bool, 'retest must be Boolean')
    integer(config['seed'], 'seed', 0, 2 ** 31 - 1)
    integer(config['timeout_seconds'], 'timeout_seconds', 1, 3600)

    def local(value):
        text(value, 'local input path', 4096)
        path = Path(value)
        return (Path(base_dir) / path).absolute()

    root, adapter = local(config['libero_root']), local(config['adapter'])
    require(adapter.suffix == '.py', 'adapter must be an explicitly selected trusted Python file')
    adapter_hash = file_hash(adapter)
    source_root = root / 'libero/libero'
    require((source_root / 'benchmark/libero_suite_task_map.py').is_file(), 'LIBERO source root is missing')
    source_hashes = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(source_root.rglob('*.py'))}
    assets = source_root / 'assets'
    require(assets.is_dir(), 'LIBERO assets are missing')
    asset_hashes = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(assets.rglob('*')) if p.is_file()}
    require(bool(asset_hashes), 'LIBERO assets directory is empty')
    # Commit labels alone do not prove unchanged code. Actual source bytes travel
    # in the plan identity and are rechecked in every worker.
    policies = {}
    for role in ('baseline', 'candidate'):
        spec = config[role]
        fields(spec, ('checkpoint', 'options'), label=role)
        require(isinstance(spec['options'], dict), f'{role}.options must be an object')
        path = local(spec['checkpoint'])
        policies[role] = {'checkpoint': str(path), 'checkpoint_sha256': file_hash(path),
                          'options': spec['options']}
    if config['change'].get('kind') == 'weights':
        require(policies['baseline']['options'] == policies['candidate']['options'],
                'weight-only evaluation requires identical adapter options')
    if config['retest']:
        policies['retest'] = policies['baseline'].copy()
    tasks = config['tasks']
    require(isinstance(tasks, list) and 1 <= len(tasks) <= 100, 'select 1–100 catalogue tasks')
    selections, seen, cells = [], set(), []
    for entry in tasks:
        fields(entry, ('id', 'states', 'max_steps', 'role', 'parent_exposure', 'update_exposure'), label='task')
        task = resolve_task(entry['id'])
        require(task['id'] not in seen, 'duplicate selected task')
        seen.add(task['id'])
        require(entry['role'] in ROLES, 'unknown task role; training exposure must be declared')
        integer(entry['max_steps'], 'max_steps', 1, 10000)
        states = entry['states']
        require(isinstance(states, list) and 1 <= len(states) <= 1000, 'select 1–1000 initial-state indices')
        for state in states:
            integer(state, 'initial-state index', 0, 999)
        require(len(set(states)) == len(states), 'duplicate initial-state index')
        stem = source_root / 'bddl_files' / task['suite'] / task['name']
        bddl = stem.with_suffix('.bddl')
        initial = source_root / 'init_files' / task['suite'] / (task['name'] + '.pruned_init')
        selection = dict(entry, name=task['name'], suite=task['suite'], task_index=task['task_index'],
                         bddl=str(bddl), bddl_sha256=file_hash(bddl),
                         init_file=str(initial), init_file_sha256=file_hash(initial))
        selections.append(selection)
        for state in states:
            identity = {'task': task['id'], 'state': state, 'seed': config['seed']}
            seed = int(sha256(encode(identity))[:8], 16) % (2 ** 31)
            for arm in policies:
                cells.append({'task': task['id'], 'state': state, 'arm': arm, 'seed': seed})
    require(len(cells) <= MAX_TRIALS, 'preview permits at most 300 planned trials per execution')
    plan = {'evaluation_schema_version': 1, 'title': config['title'], 'abi': ABI,
            'catalogue_commit': LIBERO_COMMIT, 'libero_root': str(root), 'runner_sha256': runner_hashes(),
            'adapter': str(adapter), 'adapter_sha256': adapter_hash, 'source_sha256': source_hashes,
            'asset_sha256': asset_hashes, 'runtime_versions': runtime_versions(),
            'policies': policies, 'timeout_seconds': config['timeout_seconds'],
            'tasks': selections, 'cells': cells, 'settle_steps': 10,
            'rng_identity': 'declared per-case seed schedule, not a complete RNG-state snapshot',
            'success_rule': 'official check_success after each action; stop on first success within max_steps',
            'limitations': ['Trusted local code, not a security sandbox; no generic checkpoint loading or normalization.',
                            'Runtime caps include setup and cleanup; timeout is an interruption, not task failure.',
                            'Catalogue membership does not prove competence, unseen tasks or physical generalization.']}
    contract = sha256(encode(plan))
    manifest = {'schema_version': 1, 'title': config['title'], 'evidence_origin': 'simulation',
                'change': config['change'], 'sampling': {'design': 'fixed_cases', 'frozen_before_outcomes': True,
                    'alpha': 0.05, 'maximum_harm_probability': 0.1, 'minimum_baseline_success_rate': 0.5},
                'slices': []}
    for arm, spec in policies.items():
        manifest[arm] = {'id': arm, 'family': config['family'], 'checkpoint_sha256': spec['checkpoint_sha256']}
    manifest['candidate']['parent'] = 'baseline'
    for task in selections:
        manifest['slices'].append({'id': task['id'], 'task': task['id'], 'role': task['role'],
            'condition': task['name'].replace('_', ' '), 'axis': 'nominal',
            'case_ids': [f'init-{state}' for state in task['states']], 'contract_sha256': contract,
            'horizon_steps': task['max_steps'], 'required': True,
            'parent_exposure': task['parent_exposure'], 'update_exposure': task['update_exposure']})
    validate_manifest(manifest)
    return plan, manifest


def _trial(plan_path, index, output, seconds, expected_reset=None):
    """Bound an owned worker group; preserve logs and partial actions on failure."""
    require(not (output / 'worker.log').exists(), 'trial output already exists')
    output.mkdir(exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    started = time.monotonic()
    limited, cancelled, residual_group = False, False, False
    with (output / 'worker.log').open('xb') as log:
        proc = subprocess.Popen([sys.executable, '-m', 'policydiff._libero_worker', str(plan_path),
                                 str(index), str(output), json.dumps(expected_reset)], cwd=output, env=env,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while proc.poll() is None:
                if time.monotonic() - started > seconds or log.tell() > 1024 * 1024:
                    limited = True
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            cancelled = True
        finally:
            # The leader may have exited while a same-session helper remains.
            # This group was created by this Popen; no other run is targeted.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                residual_group = True
            except ProcessLookupError:
                pass
            proc.wait()
    final, terminal = output / 'result.json', output / 'terminal.json'
    if proc.returncode == 0 and final.is_file():
        result = parse_json(read_snapshot(final), 'trial result')
    elif terminal.is_file():
        result = parse_json(read_snapshot(terminal), 'terminal record')
        result['cleanup_error'] = 'worker_stopped_after_terminal_record'
    else:
        result = {'status': 'interrupted' if limited or cancelled else 'infrastructure_error', 'success': None,
                  'reason': ('operator_cancelled' if cancelled else
                             'worker_runtime_or_log_limit' if limited else 'worker_exit_without_result')}
    if residual_group:
        result['cleanup_error'] = 'owned_worker_group_terminated'
    if cancelled:
        result['cleanup_error'] = 'operator_cancelled_worker'
    return result


def run_evaluation(config_bytes, output, *, base_dir, allow_local_code=False):
    require(allow_local_code is True, 'evaluation executes trusted adapter/checkpoint assets; pass --allow-local-code explicitly')
    config = parse_json(config_bytes, 'evaluation config')
    plan, manifest = prepare_evaluation(config, base_dir=base_dir)
    output = Path(output).absolute()
    require(not output.exists(), 'evaluation output must be a new directory')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.input.json').write_bytes(config_bytes)
    plan_data = encode(plan)
    (output / 'plan.json').write_bytes(plan_data)
    (output / 'manifest.planned.json').write_bytes(encode(manifest))
    (output / 'trials').mkdir()
    rows, results, resets = [], [], {}
    invalid_evidence = None
    for index, cell in enumerate(plan['cells']):
        require((output / 'plan.json').read_bytes() == plan_data, 'frozen execution plan changed')
        require(runner_hashes() == plan['runner_sha256'], 'PolicyDiff source changed after planning')
        trial_dir = output / 'trials' / f'{index:04d}'
        key = cell['task'], cell['state']
        result = _trial(output / 'plan.json', index, trial_dir, plan['timeout_seconds'], resets.get(key))
        (trial_dir / 'supervisor_result.json').write_bytes(encode(result))
        if cell['arm'] == 'baseline' and result.get('physical_state_sha256') and result.get('rng_sha256'):
            resets[key] = {name: result[name] for name in ('physical_state_sha256', 'rng_sha256')}
        row = dict.fromkeys(COLUMNS, '')
        row.update(revision=cell['arm'], slice=cell['task'], case=f"init-{cell['state']}",
                   status=result['status'], success=result['success'],
                   checkpoint_sha256=plan['policies'][cell['arm']]['checkpoint_sha256'],
                   contract_sha256=sha256(plan_data), physical_state_sha256=result.get('physical_state_sha256', ''),
                   rng_sha256=result.get('rng_sha256', ''), steps=result.get('steps'),
                   wall_seconds=result.get('wall_seconds'), evidence_ref=f'trials/{index:04d}/supervisor_result.json')
        rows.append(row)
        results.append({'index': index, **cell, **result})
        # Progress is recoverable evidence, never an automatic resume/retry token.
        (output / 'progress.json').write_bytes(encode({'planned_trials': len(plan['cells']), 'results': results}))
        (output / 'episodes.progress.csv').write_bytes(csv_bytes(rows))
        try:
            validate_rows(manifest, rows)
        except EvidenceError as exc:
            invalid_evidence = str(exc)
            break
        if result['status'] in ('infrastructure_error', 'interrupted') or result.get('cleanup_error'):
            break
    if invalid_evidence:
        result = {'status': 'evaluation_aborted', 'complete': False, 'output': str(output),
                  'planned_trials': len(plan['cells']), 'recorded_trials': len(rows),
                  'comparison': None, 'error': invalid_evidence, 'plan_sha256': sha256(plan_data)}
        (output / 'evaluation.json').write_bytes(encode(result))
        return result
    report = compare(manifest, rows)
    snapshots = {'manifest.input.json': encode(manifest), 'episodes.input.csv': csv_bytes(rows)}
    report['inputs'] = {'manifest_sha256': sha256(snapshots['manifest.input.json']),
                        'episodes_sha256': sha256(snapshots['episodes.input.csv'])}
    write_bundle(output / 'comparison', report, snapshots)
    result = {'status': 'evaluation_finished', 'output': str(output), 'planned_trials': len(plan['cells']),
              'recorded_trials': len(rows), 'complete': report['required_coverage_complete'],
              'plan_sha256': sha256(plan_data), 'comparison': str(output / 'comparison'),
              'observed_totals': report['observed_totals'], 'limitations': plan['limitations']}
    (output / 'evaluation.json').write_bytes(encode(result))
    return result
