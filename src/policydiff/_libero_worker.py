"""Private single-trial process. Heavy simulator/model dependencies stay optional."""
import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import sys
import time

from .execution_inputs import ABI, file_hash, libero_hashes, load_adapter, runner_hashes, runtime_versions
from .execution_records import atomic_write, receipt
from .io import encode, parse_json, read_snapshot, sha256
from .schema import require

OBSERVATION_SHAPES = {'agentview_image': (128, 128, 3), 'robot0_eye_in_hand_image': (128, 128, 3),
                      'robot0_eef_pos': (3,), 'robot0_eef_quat': (4,), 'robot0_gripper_qpos': (2,)}


def trial(plan, index, output, expected_reset=None, *, trial_id):
    plan_digest = sha256(encode(plan))
    cell = plan['cells'][index]
    task = next(item for item in plan['tasks'] if item['id'] == cell['task'])
    policy_spec = plan['policies'][cell['arm']]
    root = Path(plan['libero_root'])
    result = {'status': 'infrastructure_error', 'success': None, 'reason': 'setup_fault',
              'input_integrity': 'not_checked'}
    env, phase, inputs_checked = None, 'setup', False

    def verify_inputs():
        if runner_hashes() != plan['runner_sha256']:
            raise ValueError('PolicyDiff source changed after planning')
        if libero_hashes(root) != {key: plan[key] for key in ('source_sha256', 'asset_sha256')}:
            raise ValueError('LIBERO source or asset inventory changed after planning')
        for path, expected in ((plan['adapter'], plan['adapter_sha256']),
                               (policy_spec['checkpoint'], policy_spec['checkpoint_sha256']),
                               (task['bddl'], task['bddl_sha256']), (task['init_file'], task['init_file_sha256'])):
            if file_hash(path) != expected:
                raise ValueError('frozen input bytes changed')

    try:
        verify_inputs()
        inputs_checked = True
        config_dir = output / 'libero-config'
        config_dir.mkdir()
        dataset_dir = output / 'unused-datasets'
        dataset_dir.mkdir()
        source_root = root / 'libero/libero'
        paths = {'benchmark_root': str(source_root), 'bddl_files': str(source_root / 'bddl_files'),
                 'init_states': str(source_root / 'init_files'), 'assets': str(source_root / 'assets'),
                 'datasets': str(dataset_dir)}
        # JSON is valid YAML; do not edit the user's global LIBERO configuration.
        (config_dir / 'config.yaml').write_bytes(encode(paths))
        os.environ.update(LIBERO_CONFIG_PATH=str(config_dir), MUJOCO_GL='egl',
                          NUMBA_CACHE_DIR=str(output / 'numba-cache'), MPLCONFIGDIR=str(output / 'mpl-cache'),
                          OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
        sys.path.insert(0, str(root))
        import numpy as np
        import torch
        from libero.libero.envs import OffScreenRenderEnv

        versions = runtime_versions()
        if versions != plan['runtime_versions']:
            raise ValueError('simulator/model dependency versions changed after planning')
        if versions['robosuite'] != '1.4.1':
            raise ValueError('this experimental ABI requires robosuite 1.4.1')
        result['runtime_versions'] = versions
        torch.set_num_threads(1)
        random.seed(cell['seed'])
        np.random.seed(cell['seed'])
        torch.manual_seed(cell['seed'])
        # Upstream initial-state archives can contain pickle data. Only trusted,
        # explicitly selected local assets are allowed by the outer CLI consent.
        states = torch.load(task['init_file'], map_location='cpu', weights_only=False)
        if not 0 <= cell['state'] < len(states):
            raise ValueError('selected initial-state index is absent from this task asset')
        env = OffScreenRenderEnv(bddl_file_name=task['bddl'], robots=['Panda'],
                                controller='OSC_POSE', control_freq=20, camera_heights=128,
                                camera_widths=128, horizon=task['max_steps'] + plan['settle_steps'] + 1)
        env.seed(cell['seed'])
        env.reset()
        obs = env.set_init_state(states[cell['state']])
        for _ in range(plan['settle_steps']):
            obs, _, _, _ = env.step([0, 0, 0, 0, 0, 0, -1])
            if env.check_success():
                raise ValueError('success during initialization; no policy outcome was measured')

        def observation(value):
            selected = {}
            for name, shape in OBSERVATION_SHAPES.items():
                array = np.asarray(value[name])
                if array.shape != shape or not np.isfinite(array).all():
                    raise ValueError('observation ABI shape or numeric mismatch: ' + name)
                if name.endswith('_image') and array.dtype != np.uint8:
                    raise ValueError('image ABI requires uint8 RGB arrays')
                selected[name] = array.copy()
            return selected

        first = observation(obs)
        np.savez_compressed(output / 'initial_observation.npz', **first)

        def array_hash(value):
            array = np.ascontiguousarray(value)
            return sha256(encode({'shape': list(array.shape), 'dtype': str(array.dtype)}) + array.tobytes())

        state = {'mujoco_state': array_hash(env.get_sim_state()),
                 'ctrl': array_hash(env.sim.data.ctrl),
                 'model_xml': hashlib.sha256(env.sim.model.get_xml().encode()).hexdigest(),
                 'observations': {name: array_hash(value) for name, value in first.items()}}
        (output / 'initial_state.json').write_bytes(encode(state))
        result.update(physical_state_sha256=sha256(encode(state)), rng_sha256=sha256(encode({
            'kind': 'declared_seed_schedule', 'task': cell['task'], 'state': cell['state'], 'seed': cell['seed']})))
        if expected_reset is not None and any(result[name] != expected for name, expected in expected_reset.items()):
            raise ValueError('measured reset differs from baseline; policy was not loaded or acted')

        phase = 'adapter_load'
        module = load_adapter(plan['adapter'], plan['adapter_sha256'])
        if getattr(module, 'POLICYDIFF_ABI', None) != ABI:
            raise ValueError('adapter must declare the exact POLICYDIFF_ABI')
        if file_hash(policy_spec['checkpoint']) != policy_spec['checkpoint_sha256']:
            raise ValueError('checkpoint changed before adapter load')
        policy = module.load_policy(Path(policy_spec['checkpoint']), deepcopy(policy_spec['options']))
        if not callable(getattr(policy, 'reset', None)) or not callable(getattr(policy, 'act', None)):
            raise ValueError('adapter must return a policy with reset and act methods')
        # Task language is intended policy input, unlike BDDL/evaluator state.
        policy.reset(instruction=env.language_instruction, seed=cell['seed'], max_steps=task['max_steps'])
        low, high = env.env.action_spec
        if np.asarray(low).shape != (7,) or np.asarray(high).shape != (7,):
            raise ValueError('environment action ABI does not have seven elements')
        started = time.monotonic()
        result.update(reason='rollout_without_terminal_outcome', steps=0)
        with (output / 'actions.jsonl').open('x') as trace:
            for step in range(task['max_steps']):
                phase = 'observation'
                policy_obs = observation(obs)
                phase = 'policy_act'
                returned = policy.act(policy_obs)
                try:
                    action = np.asarray(returned)
                except (TypeError, ValueError):
                    result.update(status='policy_failure', success=False, reason='invalid_action')
                    break
                if (action.shape != (7,) or action.dtype.kind not in 'fiu' or not np.isfinite(action).all()
                        or (action < low).any() or (action > high).any()):
                    result.update(status='policy_failure', success=False, reason='invalid_action')
                    break
                action = action.astype(float)
                phase = 'environment_step'
                obs, _, done, _ = env.step(action)
                result['steps'] = step + 1
                phase = 'success_check'
                success = bool(env.check_success())
                if success or done:
                    result.update(status='completed', success=success,
                                  reason='official_success' if success else 'environment_done')
                phase = 'write_trace'
                trace.write(json.dumps({'step': step, 'action': action.tolist(), 'success': success}, allow_nan=False) + '\n')
                trace.flush()
                if success or done:
                    break
            else:
                result.update(status='completed', success=False, reason='horizon_reached')
        phase = 'finish'
        result['wall_seconds'] = time.monotonic() - started
    except (KeyboardInterrupt, SystemExit):
        if result['status'] in ('completed', 'policy_failure'):
            result['cleanup_error'] = phase + '_cancelled_after_outcome'
        else:
            result.update(status='interrupted', success=None, reason=phase + '_cancelled')
        raise
    except Exception as exc:
        # Python exceptions cannot establish causal blame. Invalid returned action
        # values are the explicitly classified policy failure above.
        error = f'{type(exc).__name__}: {exc}'[:1000]
        if result['status'] in ('completed', 'policy_failure'):
            result['cleanup_error'] = phase + '_after_outcome: ' + error
        else:
            result.update(status='infrastructure_error', success=None, reason=phase + '_exception', error=error)
    finally:
        # Persist observed outcomes before a potentially failing/hanging cleanup.
        # This is not a receipt for a clean worker exit or power-loss durability.
        try:
            if inputs_checked:
                result['input_integrity'] = 'pending'
            # Save the measured endpoint before potentially slow input sealing.
            atomic_write(output / 'terminal.json', encode(receipt(plan_digest, index, result, trial_id)))
            if inputs_checked:
                try:
                    verify_inputs()
                except Exception as exc:
                    result['input_integrity'] = 'failed'
                    result['integrity_error'] = f'input drift at trial seal: {type(exc).__name__}: {exc}'[:1000]
                else:
                    result['input_integrity'] = 'verified'
                atomic_write(output / 'terminal.json', encode(receipt(plan_digest, index, result, trial_id)))
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception as exc:
                    # Cleanup failure cannot erase an already measured terminal outcome.
                    result['cleanup_error'] = f'{type(exc).__name__}: {exc}'[:1000]
    return result


if __name__ == '__main__':
    data = read_snapshot(sys.argv[1])
    require(sha256(data) == sys.argv[5], 'execution plan bytes disagree with supervisor admission')
    plan = parse_json(data, 'execution plan')
    output = Path(sys.argv[3])
    result = trial(plan, int(sys.argv[2]), output, json.loads(sys.argv[4]), trial_id=sys.argv[6])
    atomic_write(output / 'result.json', encode(receipt(sys.argv[5], int(sys.argv[2]), result, sys.argv[6])))
