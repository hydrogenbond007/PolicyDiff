"""Synthetic external-runner structures, not robot outcomes or matched-policy evidence."""
import contextlib
from copy import deepcopy
import io
import json
import math
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from policydiff import EvidenceError, inspect_log
from policydiff.cli import main
from policydiff.io import encode, sha256
from policydiff.log_inspection import ANNOTATIONS


def fixture():
    return {'version': 1, 'status': 'success',
            'eval': {'task': 'synthetic', 'policy': 'scripted', 'embodiment': 'sim',
                     'seed': 0, 'policy_config': {}, 'embodiment_info': {}},
            'results': {'total_scenes': 1, 'total_trials': 2, 'errored_trials': 1,
                        'metrics': {'success_at_end': 1.0}},
            'samples': [{'scene_id': 's0', 'status': 'success', 'epochs': [{'success_at_end': 1.0}, {}],
                         'operator_judgements': [None, None], 'judgement_sources': [None, None],
                         'termination_reasons': ['step_limit', None], 'scene_metadata': {},
                         'trial_metadata': [{}, {}], 'reduced': {'success_at_end': 1.0}}]}


def inspect(value):
    return inspect_log(value, source_format='inspect-robots')


class LogInspectionTests(unittest.TestCase):
    def test_versioned_envelope_has_no_outcome_or_pairing_verdict(self):
        result = inspect(fixture())
        self.assertEqual(set(result), {'log_inspection_schema_version', 'status', 'producer',
            'inputs', 'source_format', 'source_schema_version', 'run_status', 'comparison_support',
            'identity_presence', 'declared_counts', 'observed_counts', 'accounting',
            'annotation_coverage', 'scorers', 'scenes', 'limitations'})
        self.assertEqual(result['log_inspection_schema_version'], 1)
        self.assertEqual(set(result['producer']), {'name', 'version'})
        self.assertEqual(result['source_schema_version'], 1)
        self.assertEqual(result['source_format'], 'inspect-robots')
        self.assertEqual(result['status'], 'log_inspected')

    def test_present_and_absent_score_records_stay_separate(self):
        result = inspect(fixture())
        self.assertEqual(result['declared_counts'], {'total_scenes': 1, 'total_trials': 2, 'errored_trials': 1})
        self.assertEqual(result['observed_counts'], {'scenes': 1, 'epoch_records': 2,
                         'scored_epoch_records': 1, 'empty_epoch_records': 1,
                         'operator_scores_without_recorded_judgement': 0})
        self.assertEqual(result['scorers'], [{'name': 'success_at_end', 'scored_epoch_records': 1,
                                            'epochs_without_score': 1}])
        self.assertEqual(result['accounting']['issues'], [])
        self.assertEqual(result['comparison_support'], 'not_established')
        self.assertIsNone(result['inputs'])
        self.assertNotIn('success_rate', result)

    def test_zero_fractional_and_negative_scores_are_recorded_not_booleanized(self):
        for value in (0, 0.0, 0.5, -2, 1e308):
            log = fixture()
            log['samples'][0]['epochs'][0] = {'custom_score': value}
            with self.subTest(value=value):
                result = inspect(log)
                self.assertEqual(result['observed_counts']['scored_epoch_records'], 1)
                self.assertEqual(result['scorers'][0]['name'], 'custom_score')
                self.assertEqual(result['comparison_support'], 'not_established')

    def test_score_coverage_uses_all_recorded_epochs_not_only_scored_epochs(self):
        log = fixture()
        log['samples'][0]['epochs'] = [{'a': 1, 'b': 0}, {'b': 0.5}]
        log['results']['errored_trials'] = 0
        self.assertEqual(inspect(log)['scorers'], [
            {'name': 'a', 'scored_epoch_records': 1, 'epochs_without_score': 1},
            {'name': 'b', 'scored_epoch_records': 2, 'epochs_without_score': 0}])

    def test_operator_score_without_annotation_is_not_treated_as_a_failure(self):
        log = fixture()
        log['samples'][0]['epochs'][0] = {'operator': 0.0}
        result = inspect(log)
        self.assertEqual(result['observed_counts']['operator_scores_without_recorded_judgement'], 1)
        self.assertEqual(result['annotation_coverage']['operator_judgements']['unannotated_epochs'], 2)
        log['samples'][0]['operator_judgements'][0] = 'failure'
        self.assertEqual(inspect(log)['observed_counts']['operator_scores_without_recorded_judgement'], 0)

    def test_absent_empty_and_aligned_all_null_annotations_remain_distinct(self):
        for name in ANNOTATIONS:
            for kind in ('absent', 'empty', 'recorded'):
                log = fixture()
                if kind == 'absent':
                    del log['samples'][0][name]
                else:
                    log['samples'][0][name] = [] if kind == 'empty' else [None, None]
                with self.subTest(name=name, kind=kind):
                    result = inspect(log)['scenes'][0]['annotations'][name]
                    self.assertEqual(result['state'], kind)
                    self.assertEqual(result['non_null'], 0)
                    self.assertEqual(result['unannotated_epochs'], 2)
                    self.assertEqual(result['null'], 2 if kind == 'recorded' else 0)

    def test_missing_error_counter_is_unknown_not_zero(self):
        log = fixture()
        del log['results']['errored_trials']
        self.assertIsNone(inspect(log)['declared_counts']['errored_trials'])

    def test_error_counters_do_not_imply_empty_score_records(self):
        log = fixture()
        log['samples'][0]['epochs'] = [{'success_at_end': 0.0}, {'success_at_end': 0.0}]
        log['results']['errored_trials'] = 2
        result = inspect(log)
        self.assertEqual(result['observed_counts']['empty_epoch_records'], 0)
        self.assertEqual(result['declared_counts']['errored_trials'], 2)
        self.assertEqual(result['accounting']['issues'], [])

    def test_error_counter_cannot_exceed_declared_trials(self):
        log = fixture()
        log['results']['errored_trials'] = 3
        self.assertEqual(inspect(log)['accounting']['issues'],
                         ['declared_errors_exceed_declared_trials'])

    def test_started_log_can_have_an_active_placeholder(self):
        log = fixture()
        log['status'] = log['samples'][0]['status'] = 'started'
        log['results']['total_trials'] = 1
        log['results']['errored_trials'] = 0
        result = inspect(log)
        self.assertEqual(result['accounting']['scope'], 'in_progress')
        self.assertIn('active epoch', result['accounting']['note'])
        self.assertIn('declared_trial_count_differs_from_recorded_epochs', result['accounting']['issues'])
        self.assertEqual(result['observed_counts']['epoch_records'], 2)

    def test_live_completed_trials_can_also_have_empty_score_records(self):
        log = fixture()
        log['status'] = 'started'
        log['results'].update(total_trials=2, errored_trials=0, metrics={})
        log['samples'][0].update(
            status='started', epochs=[{}, {}, {}], reduced={},
            operator_judgements=['success', 'failure', None],
            judgement_sources=['operator', 'operator', None],
            termination_reasons=['step_limit', 'step_limit', None],
            trial_metadata=[{}, {}, {}])
        result = inspect(log)
        self.assertEqual(result['declared_counts']['total_trials'], 2)
        self.assertEqual(result['observed_counts']['epoch_records'], 3)
        self.assertEqual(result['observed_counts']['scored_epoch_records'], 0)
        self.assertEqual(result['annotation_coverage']['operator_judgements']['non_null_epochs'], 2)
        self.assertEqual(result['scorers'], [])
        self.assertEqual(result['comparison_support'], 'not_established')
        self.assertTrue(any('completed epochs empty' in note for note in result['limitations']))
        self.assertTrue(any('process liveness' in note for note in result['limitations']))

    def test_execution_status_never_changes_score_accounting(self):
        for state in ('started', 'success', 'error', 'cancelled'):
            log = fixture()
            log['status'] = log['samples'][0]['status'] = state
            with self.subTest(state=state):
                result = inspect(log)
                self.assertEqual(result['run_status'], state)
                self.assertEqual(result['observed_counts']['scored_epoch_records'], 1)
                self.assertEqual(result['comparison_support'], 'not_established')

    def test_terminal_counter_mismatches_remain_visible_without_repair(self):
        log = fixture()
        log['results'].update(total_scenes=2, total_trials=4, errored_trials=5)
        before = deepcopy(log)
        result = inspect(log)
        self.assertEqual(result['accounting']['scope'], 'terminal')
        self.assertNotIn('active epoch', result['accounting']['note'])
        self.assertEqual(len(result['accounting']['issues']), 3)
        self.assertEqual(result['declared_counts']['total_trials'], 4)
        self.assertEqual(result['observed_counts']['epoch_records'], 2)
        self.assertEqual(log, before)

    def test_no_epochs_or_scenes_do_not_imply_a_complete_population(self):
        log = fixture()
        log['samples'] = []
        log['results'] = {'total_scenes': 0, 'total_trials': 0, 'errored_trials': 0}
        result = inspect(log)
        self.assertEqual(result['observed_counts']['epoch_records'], 0)
        self.assertEqual(result['scorers'], [])
        self.assertEqual(result['comparison_support'], 'not_established')

    def test_unknown_metadata_is_opaque_not_globally_absent_or_echoed(self):
        log = fixture()
        secret = 'DO_NOT_ECHO_PRIVATE_CONTENT'
        log['eval']['policy_config'] = {'checkpoint': secret}
        log['samples'][0]['scene_metadata'] = {'state': secret}
        log['samples'][0]['trial_metadata'][0] = {'rng': secret, 'actions': '/must/not/read'}
        log['samples'][0]['operator_notes'] = [secret]
        log['samples'][0]['policy_transcripts'] = [secret]
        log['unknown_extension'] = {'nested': secret}
        result = inspect(log)
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result['identity_presence']['policy_config'], 'recorded')
        self.assertEqual(result['scenes'][0]['metadata_presence']['scene_metadata'], 'recorded')
        self.assertEqual(result['comparison_support'], 'not_established')

    def test_identity_presence_is_not_a_validity_claim(self):
        log = fixture()
        log['eval'].update(git_commit=None, max_steps='', max_seconds=0)
        result = inspect(log)['identity_presence']
        self.assertEqual(result['git_commit'], 'null')
        self.assertEqual(result['max_steps'], 'empty')
        self.assertEqual(result['max_seconds'], 'recorded')
        self.assertEqual(result['inspect_robots_version'], 'absent')

    def test_pure_function_determinism_and_independence(self):
        log = fixture()
        before = deepcopy(log)
        one, two = inspect(log), inspect(log)
        self.assertEqual(one, two)
        self.assertEqual(log, before)
        one['scenes'][0]['annotations']['operator_judgements']['state'] = 'mutated'
        self.assertEqual(inspect(log), two)

    def test_explicit_format_and_known_integer_version_required(self):
        for value in ('unknown', None, [], 1):
            with self.subTest(format=value), self.assertRaises(EvidenceError):
                inspect_log(fixture(), source_format=value)
        for version in (True, False, 0, 2, '1', None, 1.0):
            log = fixture()
            log['version'] = version
            with self.subTest(version=version), self.assertRaises(EvidenceError):
                inspect(log)

    def test_invalid_shapes_raise_evidence_error(self):
        for key in ('eval', 'results', 'samples'):
            for value in (None, True, 1, 'bad'):
                log = fixture()
                log[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(EvidenceError):
                    inspect(log)
        for value in (None, True, [], 'bad'):
            with self.subTest(root=value), self.assertRaises(EvidenceError):
                inspect(value)

    def test_bad_counters_fail_closed(self):
        for field in ('total_scenes', 'total_trials', 'errored_trials'):
            for value in (None, True, -1, 1.5, '2', 30001):
                log = fixture()
                log['results'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(EvidenceError):
                    inspect(log)

    def test_malformed_and_misaligned_annotations_fail_closed(self):
        for name in ANNOTATIONS:
            for value in (None, {}, 'ab', [None], [None] * 3, [1, None], ['', None]):
                log = fixture()
                log['samples'][0][name] = value
                with self.subTest(name=name, value=value), self.assertRaises(EvidenceError):
                    inspect(log)

    def test_malformed_metadata_containers_fail_closed(self):
        for name, value in (('scene_metadata', None), ('scene_metadata', []),
                            ('trial_metadata', None), ('trial_metadata', [{}]),
                            ('trial_metadata', [None, {}])):
            log = fixture()
            log['samples'][0][name] = value
            with self.subTest(name=name, value=value), self.assertRaises(EvidenceError):
                inspect(log)

    def test_malformed_scores_fail_closed_at_each_scored_level(self):
        for value in (None, True, '0', math.nan, math.inf, -math.inf, 10 ** 1000, []):
            for location in ('epoch', 'reduced', 'metrics'):
                log = fixture()
                if location == 'epoch':
                    log['samples'][0]['epochs'][0] = {'score': value}
                elif location == 'reduced':
                    log['samples'][0]['reduced'] = {'score': value}
                else:
                    log['results']['metrics'] = {'score': value}
                with self.subTest(location=location, value=str(value)[:30]), self.assertRaises(EvidenceError):
                    inspect(log)

    def test_duplicate_scene_ids_do_not_silently_merge(self):
        log = fixture()
        log['samples'] *= 2
        with self.assertRaisesRegex(EvidenceError, 'duplicates'):
            inspect(log)

    def test_echoed_text_and_annotations_have_explicit_boundaries(self):
        for field, maximum in (('scene_id', 512), ('score', 200), ('operator_judgements', 200)):
            for value in ('x' * maximum, 'x' * (maximum + 1), '', ' padded ', '\x1b[31m', 'line\nbreak'):
                log = fixture()
                scene = log['samples'][0]
                if field == 'score':
                    scene['epochs'][0] = {value: 0}
                elif field == 'operator_judgements':
                    scene[field][0] = value
                else:
                    scene[field] = value
                with self.subTest(field=field, value=value[:30]):
                    if value == 'x' * maximum:
                        inspect(log)
                    else:
                        with self.assertRaises(EvidenceError):
                            inspect(log)

    def test_limits_are_global_not_only_per_scene(self):
        log = fixture()
        with patch('policydiff.log_inspection.MAX_LOG_EPOCHS', 1), self.assertRaises(EvidenceError):
            inspect(log)
        log['samples'][0]['epochs'] = [{'a': 0}, {'b': 0}]
        with patch('policydiff.log_inspection.MAX_LOG_SCORERS', 1), self.assertRaises(EvidenceError):
            inspect(log)
        with patch('policydiff.log_inspection.MAX_LOG_SCENES', 0), self.assertRaises(EvidenceError):
            inspect(log)

    def test_epoch_limit_cannot_be_bypassed_with_many_small_scenes(self):
        log = fixture()
        second = deepcopy(log['samples'][0])
        second['scene_id'] = 's1'
        log['samples'].append(second)
        log['results'].update(total_scenes=2, total_trials=3)
        with patch('policydiff.log_inspection.MAX_LOG_EPOCHS', 3):
            with self.assertRaisesRegex(EvidenceError, 'recorded epoch limit'):
                inspect(log)

    def test_randomized_accounting_against_independent_counts(self):
        rng = random.Random(80421)
        for trial in range(200):
            log = fixture()
            log['samples'] = []
            total = empty = 0
            scores = {'a': 0, 'b': 0, 'c': 0}
            annotated = 0
            for index in range(rng.randrange(1, 6)):
                scene = deepcopy(fixture()['samples'][0])
                scene['scene_id'] = f's{index}'
                scene['epochs'], scene['operator_judgements'] = [], []
                for name in ('judgement_sources', 'termination_reasons', 'trial_metadata'):
                    del scene[name]
                for _ in range(rng.randrange(8)):
                    epoch = {name: rng.choice([0, 0.5, -1]) for name in scores if rng.choice([True, False])}
                    scene['epochs'].append(epoch)
                    judgement = rng.choice([None, 'success', 'failure'])
                    scene['operator_judgements'].append(judgement)
                    total += 1
                    empty += int(len(epoch) == 0)
                    annotated += int(judgement is not None)
                    for name in scores:
                        scores[name] += int(name in epoch)
                log['samples'].append(scene)
            log['results'].update(total_scenes=len(log['samples']), total_trials=total,
                                  errored_trials=empty)
            with self.subTest(trial=trial):
                result = inspect(log)
                self.assertEqual(result['accounting']['issues'], [])
                self.assertEqual(result['observed_counts']['epoch_records'], total)
                self.assertEqual(result['observed_counts']['empty_epoch_records'], empty)
                self.assertEqual(result['observed_counts']['scored_epoch_records'], total - empty)
                self.assertEqual(result['annotation_coverage']['operator_judgements'],
                                 {'non_null_epochs': annotated, 'unannotated_epochs': total - annotated})
                self.assertEqual({x['name']: x['scored_epoch_records'] for x in result['scorers']},
                                 {name: count for name, count in scores.items() if count})
                for score in result['scorers']:
                    self.assertEqual(score['epochs_without_score'], total - scores[score['name']])
                rng.shuffle(log['samples'])
                reordered = inspect(log)
                for key in ('observed_counts', 'declared_counts', 'scorers', 'annotation_coverage'):
                    self.assertEqual(result[key], reordered[key])


class LogInspectionCLITests(unittest.TestCase):
    def invoke(self, payload):
        out, err = io.StringIO(), io.StringIO()
        with patch('policydiff.cli.read_snapshot', return_value=payload) as reader:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['inspect-log', '--format', 'inspect-robots', '--input', 'not-opened.json'])
        self.assertEqual(reader.call_count, 1)
        return code, out.getvalue(), err.getvalue()

    def test_cli_hashes_the_exact_single_read(self):
        payload = json.dumps(fixture(), indent=3).encode() + b' \n'
        code, out, err = self.invoke(payload)
        self.assertEqual((code, err), (0, ''))
        expected = inspect(fixture())
        expected['inputs'] = {'log_sha256': sha256(payload)}
        self.assertEqual(json.loads(out), expected)

    def test_duplicate_keys_nonfinite_invalid_utf8_and_deep_json(self):
        for data in (b'{"version":1,"version":1}', b'{"x":NaN}', b'{"x":1e309}',
                     b'\xff', b'[' * 2000 + b']' * 2000):
            with self.subTest(data=data[:40]):
                code, out, err = self.invoke(data)
                self.assertEqual((code, out), (2, ''))
                self.assertEqual(json.loads(err)['status'], 'invalid_input_or_output')

    def test_input_is_read_only_and_sidecars_are_not_opened(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'log.json'
            data = fixture()
            data['samples'][0]['trial_metadata'][0] = {'actions': '/does/not/exist'}
            payload = encode(data)
            path.write_bytes(payload)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['inspect-log', '--format', 'inspect-robots', '--input', str(path)]), 0)
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['log.json'])

    def test_bad_version_is_input_error_not_internal_error(self):
        data = fixture()
        data['version'] = 2
        code, out, err = self.invoke(encode(data))
        self.assertEqual((code, out), (2, ''))
        self.assertIn('version', json.loads(err)['error'])

    def test_accounting_issues_do_not_change_success_into_a_policy_verdict(self):
        data = fixture()
        data['results']['total_trials'] = 9
        code, out, err = self.invoke(encode(data))
        self.assertEqual((code, err), (0, ''))
        self.assertTrue(json.loads(out)['accounting']['issues'])
        self.assertEqual(json.loads(out)['comparison_support'], 'not_established')

    def test_output_failure_preserves_completed_inspection_context(self):
        with patch('policydiff.cli.encode', side_effect=OSError('output unavailable')):
            code, out, err = self.invoke(encode(fixture()))
        self.assertEqual((code, out), (2, ''))
        error = json.loads(err)
        self.assertEqual(error['status'], 'output_notification_failed')
        self.assertEqual(error['command'], 'inspect-log')
        self.assertEqual(error['result_status'], 'log_inspected')

    def test_cli_requires_explicit_format_and_does_not_offer_an_outcome_gate(self):
        for args in (['--input', 'log.json'], ['--format', 'inspect-robots'],
                     ['--format', 'unknown', '--input', 'log.json'],
                     ['--format', 'inspect-robots', '--input', 'log.json', '--strict-coverage']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(['inspect-log', *args])
            self.assertEqual(caught.exception.code, 2)
