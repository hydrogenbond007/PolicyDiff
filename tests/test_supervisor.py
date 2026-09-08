"""Real owned subprocess lifecycle checks, without robot/model dependencies."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from policydiff.execution import _trial
from policydiff.execution_records import receipt


@unittest.skipUnless(os.name == 'posix', 'executor requires POSIX process groups')
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def launch(self, code, seconds=2, wait_before_poll=False):
        real_popen = subprocess.Popen

        def substitute(args, **kwargs):
            self.assertEqual(kwargs['env']['PYTHONPYCACHEPREFIX'], str(self.root / 'trial/python-cache'))
            prefix = 'TRIAL_ID = ' + repr(args[-1]) + '\n'
            process = real_popen([sys.executable, '-c', prefix + code], **kwargs)
            if wait_before_poll:
                process.wait(timeout=2)
            return process

        with patch('policydiff.execution.subprocess.Popen', side_effect=substitute):
            return _trial(self.root / 'unused-plan.json', 0, self.root / 'trial', seconds,
                          plan_sha256='a' * 64, max_steps=20)

    def record(self, filename, *, success=True, steps=1, **changes):
        result = {'status': 'completed', 'success': success, 'steps': steps,
                  'input_integrity': 'verified',
                  'reason': 'official_success' if success else 'horizon_reached',
                  'physical_state_sha256': 'b' * 64, 'rng_sha256': 'c' * 64}
        packet = receipt('a' * 64, 0, result, 'placeholder')
        packet.update(changes)
        return ('from pathlib import Path; import json; value = ' + repr(packet) +
                '; value["trial_id"] = TRIAL_ID; Path(' + repr(filename) + ').write_text(json.dumps(value)); ')

    def test_clean_terminal_exit_is_not_a_cleanup_fault(self):
        result = self.launch(self.record('terminal.json') + self.record('result.json'))
        self.assertEqual((result['status'], result['success']), ('completed', True))
        self.assertNotIn('cleanup_error', result)

    def test_unexplained_exit_is_not_scored_as_failure(self):
        result = self.launch('raise SystemExit(7)')
        self.assertEqual((result['status'], result['success']), ('infrastructure_error', None))

    def test_timeout_has_no_fabricated_outcome(self):
        result = self.launch('import time; time.sleep(30)', seconds=0.15)
        self.assertEqual((result['status'], result['success']), ('interrupted', None))
        self.assertIn('cleanup_error', result)

    def test_terminal_success_survives_cleanup_timeout(self):
        code = self.record('terminal.json') + 'import time; time.sleep(30)'
        result = self.launch(code, seconds=0.2)
        self.assertEqual((result['status'], result['success'], result['steps']), ('completed', True, 1))
        self.assertIn('cleanup_error', result)

    def test_supervisor_cancellation_returns_an_accountable_interruption(self):
        with patch('policydiff.execution.time.sleep', side_effect=KeyboardInterrupt):
            result = self.launch('import time; time.sleep(30)')
        self.assertEqual((result['status'], result['success']), ('interrupted', None))
        self.assertEqual(result['reason'], 'supervisor_cancelled')

    def test_helper_is_terminated_even_after_leader_exits_cleanly(self):
        helper = 'from pathlib import Path; import time; time.sleep(0.5); Path("leaked").write_text("bad")'
        code = ('import subprocess, sys; subprocess.Popen([sys.executable, "-c", ' + repr(helper) + ']); ' +
                self.record('terminal.json') + self.record('result.json'))
        result = self.launch(code)
        self.assertTrue(result['success'])
        self.assertEqual(result['cleanup_error'], 'owned_worker_group_terminated')
        time.sleep(0.6)
        self.assertFalse((self.root / 'trial/leaked').exists())

    def test_corrupt_final_keeps_valid_terminal_and_flags_lifecycle_fault(self):
        result = self.launch(self.record('terminal.json') + 'Path("result.json").write_text("{")')
        self.assertTrue(result['success'])
        self.assertIn('cleanup_error', result)

    def test_conflicting_outcomes_never_choose_the_favorable_receipt(self):
        result = self.launch(self.record('terminal.json') + self.record('result.json', success=False, steps=20))
        self.assertIsNone(result['success'])
        self.assertIn('integrity_error', result)

    def test_wrong_trial_receipt_is_not_scored(self):
        result = self.launch(self.record('result.json', index=1))
        self.assertEqual((result['status'], result['success']), ('infrastructure_error', None))
        self.assertEqual(result['reason'], 'invalid_worker_receipt')

    def test_fast_exit_still_reports_exceeded_log_limit(self):
        code = self.record('terminal.json') + self.record('result.json') + 'import os; os.write(1, b"x" * 2097152)'
        result = self.launch(code, wait_before_poll=True)
        self.assertTrue(result['success'])
        self.assertEqual(result['supervisor']['worker_exit_code'], 0)
        self.assertTrue(result['supervisor']['limit_exceeded'])
        self.assertIn('cleanup_error', result)

    def test_sigterm_supervisor_stops_owned_worker_and_restores_handler(self):
        import signal
        previous = signal.getsignal(signal.SIGTERM)
        code = 'import os, signal, time; os.kill(os.getppid(), signal.SIGTERM); time.sleep(30)'
        result = self.launch(code)
        self.assertEqual((result['status'], result['success']), ('interrupted', None))
        self.assertTrue(result['supervisor']['cancelled'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_failed_spawn_leaves_an_admission_and_unscored_result(self):
        with patch('policydiff.execution.subprocess.Popen', side_effect=OSError('synthetic spawn failure')):
            result = _trial(self.root / 'unused', 0, self.root / 'trial', 1,
                            plan_sha256='a' * 64, max_steps=20)
        self.assertEqual((result['status'], result['success']), ('infrastructure_error', None))
        self.assertIsNone(result['supervisor']['worker_exit_code'])
        self.assertTrue((self.root / 'trial/admission.json').is_file())
