"""Opt-in local LIBERO planning and orchestration; lifecycle is supervised separately."""
from copy import deepcopy
from pathlib import Path

from .bundle import write_bundle
from .catalogue import LIBERO_COMMIT, resolve_task
from .engine import compare
from .execution_inputs import ABI, file_hash, libero_hashes, runner_hashes, runtime_versions
from .execution_records import atomic_write
from .execution_supervisor import _require_supervision, _trial
from .io import csv_bytes, encode, parse_json, sha256
from .schema import COLUMNS, ROLES, EvidenceError, fields, integer, require, text, validate_manifest, validate_rows

MAX_TRIALS = 300


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
        # Python equality conflates Boolean/integer/float options (True == 1).
        # Compare canonical JSON so a weights-only run cannot change those too.
        require(encode(policies['baseline']['options']) == encode(policies['candidate']['options']),
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
