"""Transitive import boundaries, including package exports; no robot calls."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

OPTIONAL_ROBOT_MODULES = {'torch', 'numpy', 'libero', 'mujoco'}


class ArchitectureTests(unittest.TestCase):
    def imported_modules(self, module):
        result = subprocess.run(
            [sys.executable, '-B', '-c',
             f'import {module}; import json, sys; print(json.dumps(sorted(sys.modules)))'],
            text=True, capture_output=True, timeout=10, check=True)
        return set(json.loads(result.stdout))

    def test_core_does_not_import_execution_or_optional_robot_dependencies(self):
        loaded = self.imported_modules('policydiff')
        forbidden = {'policydiff.execution', 'policydiff.execution_supervisor',
                     'policydiff._libero_worker'} | OPTIONAL_ROBOT_MODULES
        self.assertFalse(loaded & forbidden, loaded & forbidden)

    def test_worker_does_not_import_orchestration_or_reporting(self):
        loaded = self.imported_modules('policydiff._libero_worker')
        forbidden = {'policydiff.execution', 'policydiff.execution_supervisor',
                     'policydiff.bundle', 'policydiff.report', 'policydiff.cli'} | OPTIONAL_ROBOT_MODULES
        self.assertFalse(loaded & forbidden, loaded & forbidden)

    def test_supervisor_does_not_import_worker_or_report_pipeline(self):
        loaded = self.imported_modules('policydiff.execution_supervisor')
        forbidden = {'policydiff.execution', 'policydiff._libero_worker',
                     'policydiff.bundle', 'policydiff.report', 'policydiff.cli'} | OPTIONAL_ROBOT_MODULES
        self.assertFalse(loaded & forbidden, loaded & forbidden)

    def test_planner_and_worker_share_complete_source_identity(self):
        from policydiff import _libero_worker, execution, execution_inputs

        for name in ('ABI', 'runner_hashes', 'runtime_versions'):
            self.assertIs(getattr(execution, name), getattr(execution_inputs, name))
            self.assertIs(getattr(_libero_worker, name), getattr(execution_inputs, name))
        sources = execution_inputs.runner_hashes()
        root = Path(execution_inputs.__file__).parent
        required = {'execution.py', 'execution_supervisor.py', 'execution_inputs.py',
                    '_libero_worker.py', 'execution_records.py', 'io.py', 'schema.py'}
        self.assertTrue(required <= set(sources), required - set(sources))
        self.assertEqual(set(sources), {p.name for p in root.glob('*.py')})
        self.assertEqual(sources['execution_supervisor.py'],
                         hashlib.sha256((root / 'execution_supervisor.py').read_bytes()).hexdigest())
