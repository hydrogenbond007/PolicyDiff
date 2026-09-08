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


@unittest.skipUnless(os.name == 'posix', 'executor requires POSIX process groups')
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def launch(self, code, seconds=2):
        real_popen = subprocess.Popen

        def substitute(args, **kwargs):
            return real_popen([sys.executable, '-c', code], **kwargs)

        with patch('policydiff.execution.subprocess.Popen', side_effect=substitute):
            return _trial(self.root / 'unused-plan.json', 0, self.root / 'trial', seconds)

    def test_clean_terminal_exit_is_not_a_cleanup_fault(self):
        result = self.launch('from pathlib import Path; Path("result.json").write_text(' +
                             repr(json.dumps({'status': 'completed', 'success': True})) + ')')
        self.assertEqual(result, {'status': 'completed', 'success': True})

    def test_unexplained_exit_is_not_scored_as_failure(self):
        result = self.launch('raise SystemExit(7)')
        self.assertEqual((result['status'], result['success']), ('infrastructure_error', None))

    def test_timeout_has_no_fabricated_outcome(self):
        result = self.launch('import time; time.sleep(30)', seconds=0.15)
        self.assertEqual((result['status'], result['success']), ('interrupted', None))
        self.assertIn('cleanup_error', result)

    def test_terminal_success_survives_cleanup_timeout(self):
        code = ('from pathlib import Path; import time; Path("terminal.json").write_text(' +
                repr(json.dumps({'status': 'completed', 'success': True, 'steps': 1})) + '); time.sleep(30)')
        result = self.launch(code, seconds=0.2)
        self.assertEqual((result['status'], result['success'], result['steps']), ('completed', True, 1))
        self.assertIn('cleanup_error', result)

    def test_supervisor_cancellation_returns_an_accountable_interruption(self):
        with patch('policydiff.execution.time.sleep', side_effect=KeyboardInterrupt):
            result = self.launch('import time; time.sleep(30)')
        self.assertEqual((result['status'], result['success']), ('interrupted', None))
        self.assertEqual(result['reason'], 'operator_cancelled')

    def test_helper_is_terminated_even_after_leader_exits_cleanly(self):
        helper = 'from pathlib import Path; import time; time.sleep(0.5); Path("leaked").write_text("bad")'
        code = ('import subprocess, sys; from pathlib import Path; subprocess.Popen([sys.executable, "-c", ' +
                repr(helper) + ']); Path("result.json").write_text(' +
                repr(json.dumps({'status': 'completed', 'success': True})) + ')')
        result = self.launch(code)
        self.assertTrue(result['success'])
        self.assertEqual(result['cleanup_error'], 'owned_worker_group_terminated')
        time.sleep(0.6)
        self.assertFalse((self.root / 'trial/leaked').exists())
