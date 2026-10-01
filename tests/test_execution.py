"""Synthetic execution orchestration; no dependency downloads, policies or robots."""
import contextlib
from copy import deepcopy
import io
import importlib.metadata
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from policydiff import EvidenceError
from policydiff import execution, execution_supervisor
from policydiff.catalogue import resolve_task
from policydiff.cli import main
from policydiff.io import encode, sha256


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('adapter.py', 'baseline.bin', 'candidate.bin'):
            (self.root / name).write_text(name)
        backend = self.root / 'backend/libero/libero'
        for name in ('benchmark/libero_suite_task_map.py', 'assets/fixture.xml'):
            path = backend / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic source/asset')
        for task_id in ('libero_object.9', 'libero_goal.0'):
            task = resolve_task(task_id)
            for directory, suffix in (('bddl_files', '.bddl'), ('init_files', '.pruned_init')):
                path = backend / directory / task['suite'] / (task['name'] + suffix)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic test-only asset, never loaded')
        self.config = {'evaluation_schema_version': 1, 'title': 'Synthetic orchestration fixture',
                       'libero_root': 'backend', 'adapter': 'adapter.py', 'family': 'synthetic',
                       'baseline': {'checkpoint': 'baseline.bin', 'options': {}},
                       'candidate': {'checkpoint': 'candidate.bin', 'options': {}},
                       'change': {'kind': 'weights', 'description': 'Synthetic fixture; no models run.',
                                  'upstream_exposure': 'unknown'}, 'retest': True, 'seed': 17,
                       'timeout_seconds': 1, 'tasks': [{'id': 'libero_object.9', 'states': [0, 1],
                           'max_steps': 20, 'role': 'old_unrehearsed', 'parent_exposure': 'included',
                           'update_exposure': 'excluded'}]}
        self.versions = patch.object(execution, 'runtime_versions', return_value={'test': 'synthetic'})
        self.versions.start()
        self.addCleanup(self.versions.stop)

    def prepare(self, config=None):
        return execution.prepare_evaluation(self.config if config is None else config, base_dir=self.root)

    def fake_trial(self, plan_path, index, output, seconds, expected_reset=None, **kwargs):
        output.mkdir()
        cell = json.loads(plan_path.read_text())['cells'][index]
        result = {'status': 'completed', 'success': cell['arm'] != 'candidate', 'steps': 2, 'wall_seconds': 0.2,
                  'physical_state_sha256': sha256(str(cell['state']).encode()),
                  'rng_sha256': sha256(str(cell['seed']).encode())}
        if expected_reset is not None:
            self.assertEqual(expected_reset, {key: result[key] for key in expected_reset})
        return result

    def run_fake(self, trial=None):
        with patch.object(execution, '_trial', side_effect=trial or self.fake_trial):
            return execution.run_evaluation(encode(self.config), self.root / 'out', base_dir=self.root, allow_local_code=True)

    def test_plan_pairs_each_state_and_uses_actual_file_hashes(self):
        original = deepcopy(self.config)
        plan, manifest = self.prepare()
        self.assertEqual(self.config, original)
        self.assertEqual([c['arm'] for c in plan['cells']], ['baseline', 'candidate', 'retest'] * 2)
        self.assertEqual(len({c['seed'] for c in plan['cells'][:3]}), 1)
        self.assertNotEqual(plan['cells'][0]['seed'], plan['cells'][3]['seed'])
        self.assertEqual(plan['adapter_sha256'], sha256(b'adapter.py'))
        self.assertEqual(manifest['sampling']['design'], 'fixed_cases')
        self.assertEqual(manifest['candidate']['parent'], 'baseline')
        plan['policies']['baseline']['options']['mutated'] = True
        self.assertEqual(self.config, original)

    def test_selection_order_does_not_change_case_seed(self):
        first, _ = self.prepare()
        self.config['tasks'][0]['states'].reverse()
        second, _ = self.prepare()
        key = lambda c: (c['task'], c['state'], c['arm'])
        self.assertEqual({key(c): c['seed'] for c in first['cells']}, {key(c): c['seed'] for c in second['cells']})

    def test_weight_update_rejects_type_changing_adapter_options(self):
        for before, after in ((True, 1), (False, 0), (1, 1.0), (0.0, -0.0)):
            with self.subTest(before=before, after=after):
                self.config['baseline']['options'] = {'nested': [{'value': before}]}
                self.config['candidate']['options'] = {'nested': [{'value': after}]}
                with self.assertRaisesRegex(EvidenceError, 'identical adapter options'):
                    self.prepare()

    def test_weight_update_accepts_options_with_different_object_key_order(self):
        self.config['baseline']['options'] = {'outer': {'a': 1, 'b': True}, 'c': [0.5]}
        self.config['candidate']['options'] = {'c': [0.5], 'outer': {'b': True, 'a': 1}}
        self.prepare()

    def test_cli_rejects_type_changing_options_before_creating_output(self):
        self.config['baseline']['options'] = {'enabled': True}
        self.config['candidate']['options'] = {'enabled': 1}
        path = self.root / 'config.json'
        path.write_bytes(encode(self.config))
        out, err = io.StringIO(), io.StringIO()
        with patch.object(execution, '_trial') as trial, contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = main(['evaluate', '--config', str(path), '--output', str(self.root / 'out'),
                         '--allow-local-code'])
        self.assertEqual((code, out.getvalue()), (2, ''))
        self.assertIn('identical adapter options', json.loads(err.getvalue())['error'])
        trial.assert_not_called()
        self.assertFalse((self.root / 'out').exists())

    def test_full_run_creates_comparison_and_preserves_original_config(self):
        result = self.run_fake()
        self.assertTrue(result['complete'])
        self.assertEqual(result['recorded_trials'], 6)
        report = json.loads((self.root / 'out/comparison/report.json').read_text())
        self.assertEqual(report['observed_totals']['lost'], 2)
        self.assertEqual(report['eligible_slice_count'], 0)
        self.assertEqual((self.root / 'out/config.input.json').read_bytes(), encode(self.config))
        self.assertEqual(len(list((self.root / 'out/trials').glob('*/supervisor_result.json'))), 6)

    def test_infrastructure_fault_stops_admission_and_retains_missing_population(self):
        def failed(*args, **kwargs):
            result = self.fake_trial(*args, **kwargs)
            return dict(result, status='infrastructure_error', success=None, reason='fixture')
        result = self.run_fake(failed)
        self.assertFalse(result['complete'])
        self.assertEqual(result['recorded_trials'], 1)
        self.assertEqual(result['planned_trials'], 6)
        self.assertEqual(result['observed_totals']['unresolved'], 2)

    def test_cleanup_fault_preserves_success_and_stops_admission(self):
        def failed(*args, **kwargs):
            return dict(self.fake_trial(*args, **kwargs), cleanup_error='synthetic cleanup fault')
        result = self.run_fake(failed)
        self.assertEqual(result['recorded_trials'], 1)
        report = json.loads((self.root / 'out/comparison/report.json').read_text())
        self.assertEqual(report['slices'][0]['revisions']['baseline']['successes'], 1)

    def test_final_cleanup_fault_is_not_a_clean_execution_despite_full_outcomes(self):
        def last_fault(*args, **kwargs):
            result = self.fake_trial(*args, **kwargs)
            return dict(result, cleanup_error='last-cell cleanup fault') if args[1] == 5 else result
        result = self.run_fake(last_fault)
        self.assertTrue(result['complete'])
        self.assertFalse(result['execution_clean'])
        self.assertEqual(result['stop_reason'], 'trial_cleanup_or_supervision_fault')

    def test_cli_returns_nonzero_on_complete_but_unclean_execution(self):
        path = self.root / 'config.json'
        path.write_bytes(encode(self.config))
        result = {'status': 'evaluation_finished', 'complete': True, 'execution_clean': False,
                  'output': str(self.root / 'out')}
        with patch.object(execution, 'run_evaluation', return_value=result), contextlib.redirect_stdout(io.StringIO()):
            code = main(['evaluate', '--config', str(path), '--output', str(self.root / 'out'), '--allow-local-code'])
        self.assertEqual(code, 3)

    def test_first_admission_and_completed_progress_are_both_accounted(self):
        def checked(*args, **kwargs):
            progress = json.loads((self.root / 'out/progress.json').read_text())
            self.assertEqual(progress['recorded_trials'], args[1])
            self.assertEqual(progress['active_trial']['index'], args[1])
            return self.fake_trial(*args, **kwargs)
        self.run_fake(checked)
        progress = json.loads((self.root / 'out/progress.json').read_text())
        self.assertIsNone(progress['active_trial'])
        self.assertEqual(progress['recorded_trials'], 6)

    def test_changed_plan_after_final_trial_still_aborts_and_preserves_progress(self):
        def changed(*args, **kwargs):
            result = self.fake_trial(*args, **kwargs)
            if args[1] == 5:
                args[0].write_text('{}')
            return result
        result = self.run_fake(changed)
        self.assertEqual(result['status'], 'evaluation_aborted')
        self.assertEqual(result['recorded_trials'], 6)
        self.assertIn('plan changed', result['error'])
        self.assertFalse((self.root / 'out/comparison').exists())

    def test_empty_integrity_exception_still_aborts_without_comparison(self):
        real_hashes = execution.runner_hashes
        with patch.object(execution, 'runner_hashes', side_effect=[real_hashes(), OSError()]):
            result = self.run_fake()
        self.assertEqual(result['status'], 'evaluation_aborted')
        self.assertEqual(result['recorded_trials'], 0)
        self.assertFalse(result['execution_clean'])
        self.assertFalse((self.root / 'out/comparison').exists())

    def test_empty_integrity_exception_after_last_cell_does_not_publish(self):
        real_hashes = execution.runner_hashes
        # Planning, two checks per completed cell, then the final post-cell check.
        with patch.object(execution, 'runner_hashes', side_effect=[real_hashes()] * 12 + [OSError()]):
            result = self.run_fake()
        self.assertEqual(result['status'], 'evaluation_aborted')
        self.assertEqual(result['recorded_trials'], 6)
        self.assertFalse(result['execution_clean'])
        self.assertFalse((self.root / 'out/comparison').exists())

    def test_automatic_child_reaping_is_rejected_before_admission(self):
        with patch.object(execution_supervisor.signal, 'getsignal', return_value=execution_supervisor.signal.SIG_IGN), \
                self.assertRaisesRegex(EvidenceError, 'SIGCHLD'):
            self.run_fake()
        self.assertFalse((self.root / 'out').exists())

    def test_unrestorable_term_handler_is_rejected_before_admission(self):
        def handler(signum):
            return None if signum == execution_supervisor.signal.SIGTERM else execution_supervisor.signal.SIG_DFL
        with patch.object(execution_supervisor.signal, 'getsignal', side_effect=handler), \
                self.assertRaisesRegex(EvidenceError, 'restorable'):
            self.run_fake()
        self.assertFalse((self.root / 'out').exists())

    def test_per_trial_preflight_failure_publishes_abort_and_keeps_prior_rows(self):
        def changed(*args, **kwargs):
            if args[1] == 2:
                raise EvidenceError('preflight changed between trials')
            return self.fake_trial(*args, **kwargs)
        result = self.run_fake(changed)
        self.assertEqual(result['status'], 'evaluation_aborted')
        self.assertEqual(result['recorded_trials'], 2)
        self.assertFalse(result['execution_clean'])
        self.assertFalse((self.root / 'out/comparison').exists())
        self.assertEqual(json.loads((self.root / 'out/evaluation.json').read_text()), result)
        progress = json.loads((self.root / 'out/progress.json').read_text())
        self.assertEqual(progress['recorded_trials'], 2)
        self.assertFalse((self.root / 'out/trials/0002').exists())

    def test_unreadable_process_inventory_is_rejected_before_admission(self):
        with patch.object(execution_supervisor.os, 'scandir', side_effect=PermissionError('synthetic proc access')), \
                self.assertRaisesRegex(EvidenceError, '/proc'):
            self.run_fake()
        self.assertFalse((self.root / 'out').exists())

    def test_unsupported_process_supervision_fails_before_any_admission(self):
        with patch.object(execution_supervisor.sys, 'platform', 'darwin'), self.assertRaisesRegex(EvidenceError, 'Linux'):
            self.run_fake()
        self.assertFalse((self.root / 'out').exists())

    def test_input_drift_preserves_raw_outcome_but_refuses_comparison(self):
        def changed(*args, **kwargs):
            return dict(self.fake_trial(*args, **kwargs), integrity_error='synthetic input drift')
        result = self.run_fake(changed)
        self.assertEqual(result['status'], 'evaluation_aborted')
        self.assertEqual(result['recorded_trials'], 1)
        saved = json.loads((self.root / 'out/trials/0000/supervisor_result.json').read_text())
        self.assertTrue(saved['success'])
        self.assertFalse((self.root / 'out/comparison').exists())

    def test_reset_mismatch_aborts_before_the_rest_of_the_matrix(self):
        def mismatched(*args, **kwargs):
            result = self.fake_trial(*args, **kwargs)
            if args[1] == 1:
                result['physical_state_sha256'] = 'f' * 64
            return result
        result = self.run_fake(mismatched)
        self.assertEqual(result['status'], 'evaluation_aborted')
        self.assertEqual(result['recorded_trials'], 2)
        self.assertIsNone(result['comparison'])
        self.assertFalse((self.root / 'out/comparison').exists())
        self.assertTrue((self.root / 'out/episodes.progress.csv').is_file())

    def test_weight_update_cannot_silently_change_preprocessing_options(self):
        self.config['candidate']['options']['resize'] = 'different'
        with self.assertRaisesRegex(EvidenceError, 'identical adapter options'):
            self.prepare()

    def test_system_change_retains_checkpoint_but_can_change_options(self):
        self.config['change']['kind'] = 'system'
        self.config['candidate'] = {'checkpoint': 'baseline.bin', 'options': {'mode': 'changed'}}
        plan, manifest = self.prepare()
        self.assertEqual(manifest['baseline']['checkpoint_sha256'], manifest['candidate']['checkpoint_sha256'])
        self.assertNotEqual(plan['policies']['baseline']['options'], plan['policies']['candidate']['options'])

    def test_bad_versions_shapes_indices_and_exposure_fail_before_execution(self):
        for key, value in (('evaluation_schema_version', True), ('change', []), ('retest', 'yes'),
                           ('seed', True), ('timeout_seconds', 0), ('tasks', []), ('adapter', 'baseline.bin')):
            config = deepcopy(self.config)
            config[key] = value
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                self.prepare(config)
        for key, value in (('id', 'unknown.0'), ('states', [0, 0]), ('states', [True]),
                           ('states', [-1]), ('states', [1000]), ('role', 'unknown'),
                           ('parent_exposure', 'unknown'), ('max_steps', 0)):
            config = deepcopy(self.config)
            config['tasks'][0][key] = value
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                self.prepare(config)

    def test_missing_and_changed_assets_are_not_just_catalogue_labels(self):
        plan, _ = self.prepare()
        asset = self.root / 'backend/libero/libero/assets/fixture.xml'
        asset.write_text('different')
        changed, _ = self.prepare()
        self.assertNotEqual(plan['asset_sha256'], changed['asset_sha256'])
        asset.unlink()
        with self.assertRaises(EvidenceError):
            self.prepare()

    def test_explicit_trust_and_exclusive_output_are_required(self):
        with self.assertRaisesRegex(EvidenceError, 'allow-local-code'):
            execution.run_evaluation(encode(self.config), self.root / 'out', base_dir=self.root)
        self.assertFalse((self.root / 'out').exists())
        (self.root / 'out').mkdir()
        with self.assertRaisesRegex(EvidenceError, 'new directory'):
            self.run_fake()

    def test_cli_refuses_execution_without_trust_flag(self):
        path = self.root / 'config.json'
        path.write_bytes(encode(self.config))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['evaluate', '--config', str(path), '--output', str(self.root / 'out')])
        self.assertEqual((code, out.getvalue()), (2, ''))
        self.assertIn('allow-local-code', err.getvalue())

    def test_missing_optional_dependencies_are_an_input_error(self):
        self.versions.stop()
        with patch('policydiff.execution_inputs.importlib.metadata.version',
                   side_effect=importlib.metadata.PackageNotFoundError('torch')):
            with self.assertRaisesRegex(EvidenceError, 'compatible LIBERO environment'):
                self.prepare()
