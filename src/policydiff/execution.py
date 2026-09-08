"""Opt-in local LIBERO execution; separate from the pure comparison engine."""
import importlib.metadata
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from .bundle import write_bundle
from .catalogue import LIBERO_COMMIT, resolve_task
from .engine import compare
from .execution_inputs import file_hash, libero_hashes
from .execution_records import atomic_write, collect_receipts
from .io import csv_bytes, encode, parse_json, read_snapshot, sha256
from .schema import COLUMNS, ROLES, EvidenceError, fields, integer, require, text, validate_manifest, validate_rows

ABI = 'libero-panda-rgb128-proprio-osc7-v1'
MAX_TRIALS = 300
MAX_PROCESS_SCAN = 65536


def _require_supervision():
    require(sys.platform.startswith('linux') and all(hasattr(os, name) for name in
            ('waitid', 'P_PID', 'WEXITED', 'WNOWAIT', 'WNOHANG')),
            'experimental evaluation requires Linux waitid/WNOWAIT process supervision')
    require(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL,
            'evaluation requires default SIGCHLD handling and exclusive ownership of worker reaping')
    require(signal.getsignal(signal.SIGTERM) is not None,
            'evaluation requires a restorable Python SIGTERM handler')
    try:
        with os.scandir('/proc') as entries:
            next(entries, None)
        (Path('/proc') / str(os.getpid()) / 'stat').read_text()
    except OSError as exc:
        raise EvidenceError('evaluation requires a readable Linux /proc process inventory') from exc


def _live_group_members(pgid):
    """Detect a live helper while the unreaped leader still pins the group ID."""
    with os.scandir('/proc') as entries:
        for count, entry in enumerate(entries):
            if count >= MAX_PROCESS_SCAN:
                raise OSError('process inventory exceeds preview scan limit')
            if not entry.name.isdigit() or int(entry.name) == pgid:
                continue
            try:
                with (Path(entry.path) / 'stat').open() as handle:
                    data = handle.read(8193)
            except FileNotFoundError:
                continue  # Other processes may exit during this snapshot.
            parts = data.rsplit(')', 1)[-1].split()
            if len(data) > 8192 or len(parts) < 3 or not parts[2].isdigit():
                raise OSError('invalid Linux process inventory record')
            if int(parts[2]) == pgid and parts[0] not in ('Z', 'X'):
                return True
    return False


def runner_hashes():
    return {path.name: file_hash(path) for path in sorted(Path(__file__).parent.glob('*.py'))}


def runtime_versions():
    try:
        return {name: importlib.metadata.version(name) for name in ('numpy', 'torch', 'robosuite', 'mujoco')}
    except importlib.metadata.PackageNotFoundError as exc:
        raise EvidenceError('activate a compatible LIBERO environment before planning or evaluating') from exc


def prepare_evaluation(config, *, base_dir):
    """Validate an explicit run request and freeze inputs; no imports or episodes."""
    config = deepcopy(config)
    fields(config, ('evaluation_schema_version', 'title', 'libero_root', 'adapter', 'family',
                    'baseline', 'candidate', 'change', 'retest', 'seed', 'timeout_seconds', 'tasks'),
           label='evaluation')
    require(type(config['evaluation_schema_version']) is int and config['evaluation_schema_version'] == 1,
            'unsupported evaluation schema version')
    _require_supervision()
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
    inventories = libero_hashes(root)
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
            'adapter': str(adapter), 'adapter_sha256': adapter_hash, **inventories,
            'runtime_versions': runtime_versions(), 'trial_receipt_schema_version': 1,
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


@contextmanager
def _worker_signals():
    """CLI SIGTERM uses the same owned-worker cleanup path as Ctrl-C."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    require(previous is not None, 'evaluation requires a restorable Python SIGTERM handler')

    def stop(signum, frame):
        raise KeyboardInterrupt('SIGTERM')

    signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _trial(plan_path, index, output, seconds, expected_reset=None, *, plan_sha256, max_steps):
    """Bound an owned worker group; preserve logs and partial actions on failure."""
    _require_supervision()
    output.mkdir(exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    env['PYTHONPYCACHEPREFIX'] = str(output / 'python-cache')
    trial_id = uuid.uuid4().hex
    atomic_write(output / 'admission.json', encode({'index': index, 'plan_sha256': plan_sha256,
                 'trial_id': trial_id, 'expected_reset': expected_reset, 'status': 'admitted_not_proof_of_worker_start'}))
    started = time.monotonic()
    limited, cancelled, residual_group = False, False, False
    proc, supervision_error, faults = None, None, []
    with (output / 'worker.log').open('xb') as log, _worker_signals():
        try:
            proc = subprocess.Popen([sys.executable, '-m', 'policydiff._libero_worker', str(plan_path),
                                     str(index), str(output), json.dumps(expected_reset), plan_sha256, trial_id],
                                    cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is None:
                if time.monotonic() - started > seconds or os.fstat(log.fileno()).st_size > 1024 * 1024:
                    limited = True
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            cancelled = True
        except OSError as exc:
            supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
            faults.append('worker_supervision_failed')
        finally:
            # Do not poll/reap the leader before signalling. Its live/zombie PID
            # pins the PGID; after reaping that number could belong to another run.
            if proc is not None:
                try:
                    exited = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                except OSError as exc:
                    faults.append('worker_ownership_lost')
                    supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
                else:
                    try:
                        if exited is not None:
                            try:
                                residual_group = _live_group_members(proc.pid)
                            except OSError as exc:
                                faults.append('group_inventory_failed')
                                supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        faults.append('worker_group_cleanup_failed')
                        supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
                        try:
                            # The leader is still unreaped and owned here. This
                            # fallback cannot establish that helpers were stopped.
                            os.kill(proc.pid, signal.SIGKILL)
                        except OSError as fallback:
                            faults.append('worker_leader_cleanup_failed')
                            supervision_error = f'{type(fallback).__name__}: {fallback}'[:1000]
                finally:
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        faults.append('worker_reap_timeout')
        log_bytes = os.fstat(log.fileno()).st_size
    # A fast-exiting worker can cross a cap between polls. Caps are operational,
    # not a reason to erase its already recorded physical endpoint.
    limited = limited or log_bytes > 1024 * 1024 or time.monotonic() - started > seconds
    result = collect_receipts(output, plan_sha256, index, max_steps, trial_id)
    if result is None:
        result = {'status': 'interrupted' if limited or cancelled else 'infrastructure_error', 'success': None,
                  'reason': ('supervisor_cancelled' if cancelled else
                             'worker_runtime_or_log_limit' if limited else 'worker_exit_without_result')}
    if proc is not None and proc.returncode not in (None, 0):
        faults.append('worker_nonzero_exit')
    if residual_group:
        faults.append('owned_worker_group_terminated')
    if cancelled:
        faults.append('supervisor_cancelled_worker')
    if limited:
        faults.append('worker_runtime_or_log_limit')
    if faults:
        # Keep any specific receipt/worker diagnostic; supervisor faults have a
        # separate bounded vocabulary and cannot overwrite those earlier facts.
        result.setdefault('cleanup_error', '; '.join(faults))
    result['supervisor'] = {'worker_pid': proc.pid if proc is not None else None,
                            'worker_exit_code': proc.returncode if proc is not None else None,
                            'log_bytes': log_bytes, 'limit_exceeded': limited, 'cancelled': cancelled,
                            'faults': faults, 'error': supervision_error}
    return result


def run_evaluation(config_bytes, output, *, base_dir, allow_local_code=False):
    require(allow_local_code is True, 'evaluation executes trusted adapter/checkpoint assets; pass --allow-local-code explicitly')
    config = parse_json(config_bytes, 'evaluation config')
    plan, manifest = prepare_evaluation(config, base_dir=base_dir)
    output = Path(output).absolute()
    require(not output.exists(), 'evaluation output must be a new directory')
    output.mkdir(parents=True, exist_ok=False)
    atomic_write(output / 'config.input.json', config_bytes)
    plan_data = encode(plan)
    atomic_write(output / 'plan.json', plan_data)
    atomic_write(output / 'manifest.planned.json', encode(manifest))
    (output / 'trials').mkdir()
    rows, results, resets = [], [], {}
    invalid_evidence, stop_reason = None, None

    def progress(active=None):
        atomic_write(output / 'progress.json', encode({'planned_trials': len(plan['cells']),
                     'recorded_trials': len(results), 'active_trial': active, 'results': results}))
        atomic_write(output / 'episodes.progress.csv', csv_bytes(rows))

    def unchanged():
        require((output / 'plan.json').read_bytes() == plan_data, 'frozen execution plan changed')
        require(runner_hashes() == plan['runner_sha256'], 'PolicyDiff source changed after planning')

    progress()
    for index, cell in enumerate(plan['cells']):
        try:
            unchanged()
        except (EvidenceError, OSError) as exc:
            invalid_evidence = str(exc)
            break
        progress({'index': index, **cell})
        trial_dir = output / 'trials' / f'{index:04d}'
        key = cell['task'], cell['state']
        horizon = next(task['max_steps'] for task in plan['tasks'] if task['id'] == cell['task'])
        try:
            result = _trial(output / 'plan.json', index, trial_dir, plan['timeout_seconds'], resets.get(key),
                            plan_sha256=sha256(plan_data), max_steps=horizon)
        except (EvidenceError, OSError) as exc:
            invalid_evidence = str(exc)
            break
        atomic_write(trial_dir / 'supervisor_result.json', encode(result))
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
        progress()
        try:
            require(not result.get('integrity_error'), result.get('integrity_error', 'worker integrity fault'))
            validate_rows(manifest, rows)
            unchanged()
        except (EvidenceError, OSError) as exc:
            invalid_evidence = str(exc)
            break
        if result['status'] in ('infrastructure_error', 'interrupted') or result.get('cleanup_error'):
            stop_reason = result['reason'] if not result.get('cleanup_error') else 'trial_cleanup_or_supervision_fault'
            break
    if invalid_evidence is not None:
        result = {'status': 'evaluation_aborted', 'complete': False, 'output': str(output),
                  'planned_trials': len(plan['cells']), 'recorded_trials': len(rows),
                  'comparison': None, 'error': invalid_evidence, 'plan_sha256': sha256(plan_data),
                  'execution_clean': False, 'stop_reason': 'evidence_integrity_fault'}
        atomic_write(output / 'evaluation.json', encode(result))
        return result
    report = compare(manifest, rows)
    snapshots = {'manifest.input.json': encode(manifest), 'episodes.input.csv': csv_bytes(rows)}
    report['inputs'] = {'manifest_sha256': sha256(snapshots['manifest.input.json']),
                        'episodes_sha256': sha256(snapshots['episodes.input.csv'])}
    write_bundle(output / 'comparison', report, snapshots)
    result = {'status': 'evaluation_finished', 'output': str(output), 'planned_trials': len(plan['cells']),
              'recorded_trials': len(rows), 'complete': report['required_coverage_complete'],
              'execution_clean': stop_reason is None, 'stop_reason': stop_reason,
              'plan_sha256': sha256(plan_data), 'comparison': str(output / 'comparison'),
              'observed_totals': report['observed_totals'], 'limitations': plan['limitations']}
    atomic_write(output / 'evaluation.json', encode(result))
    return result
