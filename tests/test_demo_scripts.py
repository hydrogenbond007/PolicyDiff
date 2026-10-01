"""The optional demo adapter stays deterministic and requires no simulator import."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('demo_policy', SCRIPTS / 'demo_policy.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
spec = importlib.util.spec_from_file_location('record_sim_demo', SCRIPTS / 'record_sim_demo.py')
recording = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recording)


class DemoPolicyTests(unittest.TestCase):
    def test_fault_changes_only_gripper_and_does_not_mutate_source_actions(self):
        actions = [[.1, .2, .3, .4, .5, .6, 1]]
        before, after = demo.ReplayPolicy(actions), demo.ReplayPolicy(actions, True)
        for policy in (before, after):
            policy.reset(instruction='demo', seed=17, max_steps=3)
        self.assertEqual(before.act({}), actions[0])
        self.assertEqual(after.act({}), actions[0][:-1] + [-1])
        self.assertEqual(actions[0][-1], 1)
        self.assertEqual(after.act({}), [0, 0, 0, 0, 0, 0, -1])

    def test_reset_restarts_sequence_and_returned_actions_are_detached(self):
        policy = demo.ReplayPolicy([[0, 0, 0, 0, 0, 0, 1]])
        for _ in range(2):
            policy.reset(instruction='demo', seed=17, max_steps=1)
            action = policy.act({})
            self.assertEqual(action[-1], 1)
            action[-1] = -1

    def test_load_explicit_json_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'controller.json'
            path.write_text(json.dumps({'actions': [[0, 0, 0, 0, 0, 0, 1]]}))
            policy = demo.load_policy(path, {'disable_gripper': True})
            policy.reset(instruction='demo', seed=17, max_steps=1)
            self.assertEqual(policy.act({})[-1], -1)

    def test_demo_help_does_not_require_optional_dependencies(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'record_sim_demo.py'), '--help'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--libero-root', result.stdout)

    def test_replay_requires_complete_ordered_trace_and_sealed_endpoint(self):
        trace = [{'step': 0, 'success': False}, {'step': 1, 'success': True}]
        result = {'status': 'completed', 'input_integrity': 'verified', 'steps': 2, 'success': True}
        recording.check_trace(trace, result, 2)
        for bad in ([], trace[:1], list(reversed(trace)),
                    [{'step': 0, 'success': True}, {'step': 1, 'success': True}],
                    [{'step': 0, 'success': False}, {'step': 1, 'success': False}]):
            with self.subTest(trace=bad), self.assertRaises(ValueError):
                recording.check_trace(bad, result, 2)
        for changes in ({'input_integrity': 'pending'}, {'status': 'interrupted'}, {'steps': 3}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                recording.check_trace(trace, dict(result, **changes), 2)
        with self.assertRaises(ValueError):
            recording.check_trace(trace, result, 1)
