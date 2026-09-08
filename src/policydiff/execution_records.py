"""Bounded worker transport and atomic local checkpoints, not authentication."""
import math
import os
from pathlib import Path
import tempfile

from .io import encode, parse_json, read_snapshot
from .schema import EvidenceError, fields, integer, require, sha, text

MAX_RECEIPT_BYTES = 32768


def atomic_write(path, data):
    """Publish one complete file. Not a cross-file or power-loss transaction."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            require(handle.write(data) == len(data), 'short checkpoint write')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def receipt(plan_sha256, index, result, trial_id):
    return {'trial_receipt_schema_version': 1, 'plan_sha256': plan_sha256,
            'index': index, 'trial_id': trial_id, 'result': result}


def read_receipt(path, plan_sha256, index, max_steps, trial_id):
    require(not path.is_symlink(), 'worker receipt must not be a symlink')
    value = parse_json(read_snapshot(path, maximum=MAX_RECEIPT_BYTES), 'worker receipt')
    fields(value, ('trial_receipt_schema_version', 'plan_sha256', 'index', 'trial_id', 'result'), label='worker receipt')
    require(type(value['trial_receipt_schema_version']) is int and value['trial_receipt_schema_version'] == 1,
            'unsupported worker receipt version')
    require(sha(value['plan_sha256'], 'worker plan digest') == plan_sha256, 'worker receipt belongs to another plan')
    integer(value['index'], 'worker cell index', 0, 299)
    require(value['index'] == index, 'worker receipt belongs to another trial')
    text(value['trial_id'], 'worker trial identity', 64)
    require(value['trial_id'] == trial_id, 'worker receipt belongs to another admission')
    result = value['result']
    fields(result, ('status', 'success', 'reason', 'input_integrity'), optional=('steps', 'wall_seconds', 'physical_state_sha256',
           'rng_sha256', 'runtime_versions', 'error', 'cleanup_error', 'integrity_error'), label='worker result')
    require(result['status'] in ('completed', 'policy_failure', 'infrastructure_error', 'interrupted'),
            'unknown worker status')
    text(result['reason'], 'worker reason', 200)
    outcome = result['status'] in ('completed', 'policy_failure')
    require(result['input_integrity'] in ('not_checked', 'pending', 'verified', 'failed'), 'unknown input-seal status')
    require(not outcome or result['input_integrity'] != 'not_checked', 'outcome lacks initial input verification')
    require(result['input_integrity'] != 'failed' or bool(result.get('integrity_error')), 'failed seal needs a diagnostic')
    require(type(result['success']) is bool if outcome else result['success'] is None,
            'worker outcome must be Boolean; a non-outcome must be null')
    require(result['status'] != 'policy_failure' or result['success'] is False, 'policy failure cannot succeed')
    for name in ('physical_state_sha256', 'rng_sha256'):
        if outcome or name in result:
            sha(result.get(name), name)
    if outcome or 'steps' in result:
        integer(result.get('steps'), 'worker steps', 0, max_steps)
    if 'wall_seconds' in result:
        seconds = result['wall_seconds']
        require(type(seconds) in (int, float) and 0 <= seconds <= 1e9 and math.isfinite(seconds),
                'invalid worker elapsed time')
    if result['status'] == 'completed':
        require(result['steps'] > 0, 'completion needs at least one executed action')
        reasons = ('official_success',) if result['success'] else ('horizon_reached', 'environment_done')
        require(result['reason'] in reasons, 'completed outcome contradicts terminal reason')
        if result['reason'] == 'horizon_reached':
            require(result['steps'] == max_steps, 'horizon failure must exhaust the declared budget')
    if result['status'] == 'policy_failure':
        require(result['reason'] == 'invalid_action' and result['steps'] < max_steps,
                'invalid action must occur before the action budget is exhausted')
    for name in ('error', 'cleanup_error', 'integrity_error'):
        if name in result:
            require(isinstance(result[name], str) and 0 < len(result[name]) <= 2048, 'invalid worker diagnostic')
    if 'runtime_versions' in result:
        versions = result['runtime_versions']
        fields(versions, ('numpy', 'torch', 'robosuite', 'mujoco'), label='worker runtime versions')
        for version in versions.values():
            text(version, 'worker dependency version', 100)
    return result


def collect_receipts(output, plan_sha256, index, max_steps, trial_id):
    """Retain a valid endpoint through cleanup damage; never choose conflicting outcomes."""
    records, errors = {}, []
    for name in ('terminal.json', 'result.json'):
        path = output / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            records[name] = read_receipt(path, plan_sha256, index, max_steps, trial_id)
        except (EvidenceError, OSError) as exc:
            errors.append(f'{name}: {str(exc)[:250]}')
    if len(records) == 2:
        comparable = [{k: v for k, v in records[name].items() if k != 'cleanup_error'} for name in records]
        if comparable[0] != comparable[1]:
            return {'status': 'infrastructure_error', 'success': None, 'reason': 'worker_receipt_conflict',
                    'integrity_error': 'pre-cleanup and final worker receipts disagree'}
    result = records.get('result.json', records.get('terminal.json'))
    if result is None:
        if errors:
            return {'status': 'infrastructure_error', 'success': None, 'reason': 'invalid_worker_receipt',
                    'error': '; '.join(errors)}
        return None
    cleanup_errors = {name: record['cleanup_error'] for name, record in records.items()
                      if 'cleanup_error' in record}
    if cleanup_errors:
        result['receipt_cleanup_errors'] = cleanup_errors
        result.setdefault('cleanup_error', next(iter(cleanup_errors.values())))
    if errors or len(records) != 2:
        result['receipt_errors'] = errors or ['worker_receipt_incomplete']
        result.setdefault('cleanup_error', '; '.join(result['receipt_errors']))
    if result['input_integrity'] == 'pending':
        result['integrity_error'] = 'input verification did not finish; measured endpoint retained but comparison blocked'
    return result
