"""Control-flow tests with mocked numerical/simulator modules, not robot trials."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from policydiff import _libero_worker as worker


class WorkerBoundaryTests(unittest.TestCase):
    def run_worker(self, action=None, cancellation=None, expected_reset=None, close_error=None,
                   finishing_exception=None, outcome_success=False, seal_drift=False, terminal_write_error=False,
                   seal_interrupt=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name)

        def array(shape):
            value = MagicMock()
            value.shape = shape
            value.dtype = 'uint8'
            value.copy.return_value = value
            value.tobytes.return_value = b'synthetic array'
            return value

        np, torch, env, module = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        np.uint8 = 'uint8'
        def asarray(value):
            if isinstance(value, list):
                raise ValueError('synthetic ragged-array conversion')
            return value

        np.asarray.side_effect = asarray
        np.ascontiguousarray.side_effect = lambda value: value
        np.isfinite.return_value.all.return_value = True
        torch.load.return_value = [[]]
        obs = {name: array(shape) for name, shape in worker.OBSERVATION_SHAPES.items()}
        env.set_init_state.return_value = obs
        env.step.return_value = (obs, 0, False, {})
        env.check_success.side_effect = [False, outcome_success]
        env.get_sim_state.return_value = array((10,))
        env.sim.data.ctrl = array((7,))
        env.sim.model.get_xml.return_value = '<synthetic/>'
        env.env.action_spec = (array((7,)), array((7,)))
        env.close.side_effect = close_error
        module.POLICYDIFF_ABI = worker.ABI
        policy = module.load_policy.return_value
        policy.act.side_effect = cancellation
        policy.act.return_value = action
        plan = {'cells': [{'task': 'fixture', 'arm': 'baseline', 'state': 0, 'seed': 1}],
                'tasks': [{'id': 'fixture', 'bddl': 'task', 'bddl_sha256': 'h',
                           'init_file': 'states', 'init_file_sha256': 'h', 'max_steps': 1}],
                'policies': {'baseline': {'checkpoint': 'checkpoint', 'checkpoint_sha256': 'h', 'options': {}}},
                'adapter': 'adapter.py', 'adapter_sha256': 'h', 'libero_root': str(output),
                'runner_sha256': {}, 'source_sha256': {}, 'asset_sha256': {},
                'runtime_versions': {'robosuite': '1.4.1'}, 'settle_steps': 1}
        fake_envs = SimpleNamespace(OffScreenRenderEnv=MagicMock(return_value=env))
        with patch.dict('sys.modules', {'numpy': np, 'torch': torch, 'libero.libero.envs': fake_envs}), \
                patch.object(worker, 'file_hash', return_value='h'), \
                patch.object(worker, 'runner_hashes', side_effect=[{}, KeyboardInterrupt('during seal') if seal_interrupt else {}]), \
                patch.object(worker, 'libero_hashes', side_effect=[{'source_sha256': {}, 'asset_sha256': {}},
                    {'source_sha256': {'changed': 'h'} if seal_drift else {}, 'asset_sha256': {}}]), \
                patch.object(worker, 'runtime_versions', return_value=plan['runtime_versions']), \
                patch.object(worker, 'load_adapter', return_value=module), \
                patch.dict('os.environ'), patch.object(worker.sys, 'path', worker.sys.path.copy()), \
                patch.dict('sys.modules'), \
                patch.object(worker.time, 'monotonic', side_effect=[0.0, finishing_exception or 1.0]), \
                patch.object(worker, 'atomic_write', wraps=worker.atomic_write,
                             side_effect=OSError('synthetic terminal write fault') if terminal_write_error else None):
            interruption = KeyboardInterrupt() if seal_interrupt else cancellation or finishing_exception
            if terminal_write_error:
                with self.assertRaisesRegex(OSError, 'terminal write fault'):
                    worker.trial(plan, 0, output, expected_reset, trial_id='synthetic-admission')
                env.close.assert_called_once()
                return {}, policy, output
            if isinstance(interruption, (SystemExit, KeyboardInterrupt)):
                with self.assertRaises(type(interruption)):
                    worker.trial(plan, 0, output, expected_reset, trial_id='synthetic-admission')
                result = json.loads((output / 'terminal.json').read_text())['result']
            else:
                result = worker.trial(plan, 0, output, expected_reset, trial_id='synthetic-admission')
        return result, policy, output

    def test_system_exit_is_not_a_horizon_failure(self):
        result, _, _ = self.run_worker(cancellation=SystemExit(0))
        self.assertEqual((result['status'], result['success']), ('interrupted', None))
        self.assertEqual(result['reason'], 'policy_act_cancelled')

    def test_keyboard_interrupt_is_not_a_horizon_failure(self):
        result, _, _ = self.run_worker(cancellation=KeyboardInterrupt())
        self.assertEqual((result['status'], result['success']), ('interrupted', None))

    def test_reset_mismatch_never_loads_or_calls_policy(self):
        result, policy, _ = self.run_worker(expected_reset={'physical_state_sha256': 'different'})
        self.assertEqual((result['status'], result['success']), ('infrastructure_error', None))
        policy.reset.assert_not_called()
        policy.act.assert_not_called()

    def test_wrong_action_shape_is_preserved_through_cleanup_error(self):
        action = SimpleNamespace(shape=(2,))
        result, _, output = self.run_worker(action=action, close_error=RuntimeError('cleanup fixture'))
        self.assertEqual((result['status'], result['success']), ('policy_failure', False))
        self.assertIn('cleanup_error', result)
        terminal = json.loads((output / 'terminal.json').read_text())['result']
        self.assertEqual((terminal['status'], terminal['success']), ('policy_failure', False))
        self.assertNotIn('cleanup_error', terminal)

    def test_ragged_conversion_is_an_explicit_policy_failure(self):
        result, _, _ = self.run_worker(action=[[0], [1, 2]])
        self.assertEqual((result['status'], result['success'], result['reason']),
                         ('policy_failure', False, 'invalid_action'))

    def valid_action(self):
        action = MagicMock()
        action.shape = (7,)
        action.dtype.kind = 'f'
        action.__lt__.return_value = MagicMock()
        action.__gt__.return_value = MagicMock()
        action.__lt__.return_value.any.return_value = False
        action.__gt__.return_value.any.return_value = False
        action.astype.return_value = action
        action.tolist.return_value = [0, 0, 0, 0, 0, 0, -1]
        return action

    def test_late_cancellation_preserves_measured_success(self):
        result, _, _ = self.run_worker(action=self.valid_action(), outcome_success=True,
                                       finishing_exception=KeyboardInterrupt())
        self.assertEqual((result['status'], result['success'], result['reason']),
                         ('completed', True, 'official_success'))
        self.assertIn('cleanup_error', result)

    def test_late_cancellation_preserves_invalid_action_failure(self):
        result, _, _ = self.run_worker(action=SimpleNamespace(shape=(2,)), finishing_exception=SystemExit(0))
        self.assertEqual((result['status'], result['success']), ('policy_failure', False))
        self.assertIn('cleanup_error', result)

    def test_late_bookkeeping_exception_preserves_measured_success(self):
        result, _, _ = self.run_worker(action=self.valid_action(), outcome_success=True,
                                       finishing_exception=OSError('synthetic bookkeeping error'))
        self.assertEqual((result['status'], result['success']), ('completed', True))
        self.assertIn('cleanup_error', result)

    def test_source_drift_at_seal_retains_outcome_but_marks_integrity_fault(self):
        result, _, _ = self.run_worker(action=self.valid_action(), outcome_success=True, seal_drift=True)
        self.assertEqual((result['status'], result['success']), ('completed', True))
        self.assertIn('input drift at trial seal', result['integrity_error'])

    def test_terminal_write_failure_still_closes_environment(self):
        self.run_worker(action=self.valid_action(), outcome_success=True, terminal_write_error=True)

    def test_interrupted_seal_preserves_success_but_does_not_assert_input_integrity(self):
        result, _, _ = self.run_worker(action=self.valid_action(), outcome_success=True, seal_interrupt=True)
        self.assertTrue(result['success'])
        self.assertEqual(result['input_integrity'], 'pending')
