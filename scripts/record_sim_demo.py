"""CPU-capable LIBERO walkthrough: calibrate a script, evaluate a fault, record replay.

Requires the optional LIBERO runtime plus Pillow and imageio-ffmpeg. No model API,
trained weights, downloads, or arbitrary task support. See docs/SIMULATION_DEMO.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys


def check_trace(trace, result, horizon):
    """A partial/empty trace is not a verified recording of a completed trial."""
    if (result['status'] != 'completed' or result['input_integrity'] != 'verified'
            or not 0 < len(trace) == result['steps'] <= horizon
            or [row['step'] for row in trace] != list(range(len(trace)))
            or any(type(row['success']) is not bool for row in trace)
            or any(row['success'] for row in trace[:-1])
            or trace[-1]['success'] != result['success']):
        raise ValueError('trace does not match a complete sealed first-success trial')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libero-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('prepare', 'record'), required=True)
    args = parser.parse_args()
    root, out = args.libero_root.resolve(), args.output.resolve()
    if args.stage == 'prepare':
        out.mkdir(parents=True, exist_ok=False)
    os.environ.update(MUJOCO_GL='egl', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                      LIBERO_CONFIG_PATH=str(out / 'libero-config'))
    sys.path.insert(0, str(root))
    from policydiff.catalogue import resolve_task
    from policydiff.io import encode, sha256
    source = root / 'libero/libero'
    config_dir = out / 'libero-config'
    if args.stage == 'prepare':
        config_dir.mkdir()
        (config_dir / 'config.yaml').write_bytes(encode({
            'benchmark_root': str(source), 'bddl_files': str(source / 'bddl_files'),
            'init_states': str(source / 'init_files'), 'assets': str(source / 'assets'),
            'datasets': str(out / 'unused-datasets')}))
    import numpy as np
    import torch
    from libero.libero.envs import OffScreenRenderEnv
    torch.set_num_threads(1)
    task = resolve_task('libero_spatial.0')
    task_file = source / 'bddl_files/libero_spatial' / (task['name'] + '.bddl')
    states = torch.load(source / 'init_files/libero_spatial' / (task['name'] + '.pruned_init'),
                        map_location='cpu', weights_only=False)
    seed = int(sha256(encode({'task': task['id'], 'state': 0, 'seed': 17}))[:8], 16) % (2 ** 31)

    def reset():
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        env = OffScreenRenderEnv(bddl_file_name=str(task_file), robots=['Panda'], controller='OSC_POSE',
                                control_freq=20, camera_heights=128, camera_widths=128, horizon=1011)
        env.seed(seed)
        env.reset()
        obs = env.set_init_state(states[0])
        for _ in range(10):
            obs, _, _, _ = env.step([0, 0, 0, 0, 0, 0, -1])
            if env.check_success():
                raise RuntimeError('success before controller execution')
        return env, obs

    if args.stage == 'prepare':
        env, obs = reset()
        actions = []
        try:
            sim = env.sim
            body = lambda name: sim.data.body_xpos[sim.model.body_name2id(name)].copy()
            eef = lambda: obs['robot0_eef_pos'].copy()
            bowl, plate = body('akita_black_bowl_1_main'), body('plate_1_main')
            bid = sim.model.body_name2id('akita_black_bowl_1_main')
            geoms = [i for i in range(sim.model.ngeom) if sim.model.geom_bodyid[i] == bid
                     and (sim.model.geom_contype[i] or sim.model.geom_conaffinity[i])]
            radius = max(np.linalg.norm(sim.data.geom_xpos[i][:2] - bowl[:2]) for i in geoms)
            top = max(sim.data.geom_xpos[i][2] for i in geoms)
            pads = [sim.data.geom_xpos[sim.model.geom_name2id('gripper0_finger%d_pad_collision' % i)]
                    for i in (1, 2)]
            axis = (pads[0] - pads[1])[:2]
            axis /= np.linalg.norm(axis)
            grasp = bowl[:2] + axis * radius * 0.8

            def step(action):
                nonlocal obs
                obs, _, _, _ = env.step(action)
                actions.append([float(v) for v in action])

            def move(target, grip, cap, clip, tolerance=.008):
                for _ in range(cap):
                    error = np.array(target) - eef()
                    if max(abs(error[:2])) < .006 and abs(error[2]) < tolerance:
                        break
                    step([*np.clip(error * 12, -clip, clip), 0, 0, 0, grip])

            def hold(grip, count):
                for _ in range(count):
                    step([0, 0, 0, 0, 0, 0, grip])

            move([*grasp, top + .13], -1, 160, .6)
            move([*grasp, top - .008], -1, 120, .2, .004)
            hold(1, 20)
            move([*eef()[:2], top + .13], 1, 120, .25)
            carry = plate[:2] + eef()[:2] - body('akita_black_bowl_1_main')[:2]
            move([*carry, top + .13], 1, 160, .35)
            move([*carry, plate[2] + .055], 1, 200, .1, .005)
            hold(-1, 25)
            move(eef() + [0, 0, .12], -1, 120, .2)
            hold(-1, 40)
            if len(actions) > 1000:
                raise RuntimeError('calibration exceeds frozen 1000-step demonstration budget')
            (out / 'controller.json').write_bytes(encode({'actions': actions,
                'provenance': 'Privileged scripted calibration on LIBERO Spatial 0, init 0; not trained weights.'}))
        finally:
            env.close()
        config = {'evaluation_schema_version': 1, 'title': 'Scripted gripper-fault demonstration',
            'libero_root': str(root), 'adapter': str(Path(__file__).with_name('demo_policy.py').resolve()),
            'family': 'scripted-action-replay', 'baseline': {'checkpoint': 'controller.json', 'options': {}},
            'candidate': {'checkpoint': 'controller.json', 'options': {'disable_gripper': True}},
            'change': {'kind': 'system', 'description': 'Deliberately hold the gripper open; no weight update.',
                       'upstream_exposure': 'unknown'}, 'retest': True, 'seed': 17, 'timeout_seconds': 300,
            'tasks': [{'id': task['id'], 'states': [0], 'max_steps': 1000, 'role': 'old_rehearsed',
                       'parent_exposure': 'included', 'update_exposure': 'included'}]}
        (out / 'evaluation-config.json').write_bytes(encode(config))
        print('Prepared explicit one-start development demonstration:', out)
        return

    # Record all three evaluated arms, not a selected success; verify every flag.
    import imageio.v2 as imageio
    from policydiff._libero_worker import OBSERVATION_SHAPES
    from policydiff.execution_inputs import ABI, runtime_versions
    plan = json.loads((out / 'evaluation/plan.json').read_text())
    if (len(plan['cells']) != 3 or plan['settle_steps'] != 10 or
            plan['abi'] != ABI or plan['libero_root'] != str(root) or
            plan['runtime_versions'] != runtime_versions() or len(plan['tasks']) != 1 or
            plan['tasks'][0]['max_steps'] != 1000 or
            any(cell != {'task': task['id'], 'state': 0, 'seed': seed, 'arm': arm}
                for cell, arm in zip(plan['cells'], ('baseline', 'candidate', 'retest')))):
        raise RuntimeError('recording supports only this exact demonstration plan')
    recording_dir = out / 'replay'
    recording_dir.mkdir(exist_ok=False)
    recordings = []
    for index, cell in enumerate(plan['cells']):
        trial = out / 'evaluation/trials' / f'{index:04d}'
        trace = [json.loads(line) for line in (trial / 'actions.jsonl').read_text().splitlines()]
        result = json.loads((trial / 'supervisor_result.json').read_text())
        check_trace(trace, result, 1000)
        env, obs = reset()
        video = recording_dir / (cell['arm'] + '.mp4')
        try:
            initial = json.loads((trial / 'initial_state.json').read_text())

            def array_hash(value):
                array = np.ascontiguousarray(value)
                return sha256(encode({'shape': list(array.shape), 'dtype': str(array.dtype)}) + array.tobytes())

            observed = {'mujoco_state': array_hash(env.get_sim_state()), 'ctrl': array_hash(env.sim.data.ctrl),
                'model_xml': hashlib.sha256(env.sim.model.get_xml().encode()).hexdigest(),
                'observations': {name: array_hash(obs[name]) for name in OBSERVATION_SHAPES}}
            if initial != observed:
                raise RuntimeError('recording reset differs from evaluated reset')
            with imageio.get_writer(video, fps=20, codec='libx264', macro_block_size=1) as writer:
                writer.append_data(obs['agentview_image'][::-1])
                for row in trace:
                    obs, _, _, _ = env.step(row['action'])
                    if bool(env.check_success()) != row['success']:
                        raise RuntimeError('recording replay disagrees with measured success trace')
                    writer.append_data(obs['agentview_image'][::-1])
        finally:
            env.close()
        recordings.append({'arm': cell['arm'], 'frames': len(trace) + 1,
                           'sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'file': video.name,
                           'reset_matches': True, 'steps_checked': len(trace),
                           'per_step_success_matches': True})
    (recording_dir / 'recordings.json').write_bytes(encode({'recordings': recordings,
        'plan_sha256': sha256((out / 'evaluation/plan.json').read_bytes()),
        'scope': 'Post-run physics replay; 20 control steps per playback second, not inference wall time.'}))


if __name__ == '__main__':
    main()
