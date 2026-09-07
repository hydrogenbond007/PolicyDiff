"""A displayed subset must never become a cherry-picked statistical population."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from policydiff import EvidenceError, compare
from policydiff.cli import main
from policydiff.demo import fixture
from policydiff.io import csv_bytes, encode
from policydiff.triage import TRANSITIONS, select_cases
from test_engine import inferential


class TriageTests(unittest.TestCase):
    def test_default_is_exact_changed_and_unresolved_partition(self):
        report = compare(*fixture())
        view = select_cases(report, limit=10000)
        expected = [dict(case, slice=sl['id']) for sl in report['slices'] for case in sl['cases']
                    if case['transition'] in ('lost', 'gained', 'unresolved')]
        self.assertEqual(view['cases'], expected)
        self.assertEqual(view['selection']['matching_cases'], len(expected))
        self.assertFalse(view['selection']['truncated'])
        self.assertEqual(view['comparison']['observed_totals'], report['observed_totals'])
        self.assertEqual(view['comparison']['evidence_origin'], 'synthetic')
        self.assertIsNone(view['comparison']['has_inferential_regression'])
        self.assertNotIn('manifest', view['comparison'])
        self.assertNotIn('slices', view['comparison'])
        self.assertEqual(view['comparison']['report_schema_version'], report['report_schema_version'])

    def test_filter_keeps_all_slices_and_unfiltered_evidence(self):
        report = compare(*fixture())
        sid = report['slices'][0]['id']
        view = select_cases(report, slice_ids=[sid], transitions=['lost'])
        self.assertTrue(all(c['slice'] == sid and c['transition'] == 'lost' for c in view['cases']))
        for original, sl in zip(report['slices'], view['slices']):
            self.assertEqual(sl['selected_for_display'], sl['id'] == sid)
            self.assertEqual({k: sl[k] for k in original if k != 'cases'},
                             {k: v for k, v in original.items() if k != 'cases'})
        self.assertEqual(len(view['slices']), len(report['slices']))
        self.assertIn('not_tested', [sl['coverage'] for sl in view['slices']])

    def test_empty_match_does_not_claim_no_losses_globally(self):
        report = compare(*fixture())
        sid = report['slices'][-1]['id']
        view = select_cases(report, slice_ids=[sid], transitions=['lost'])
        self.assertEqual(view['cases'], [])
        self.assertGreater(view['comparison']['observed_totals']['lost'], 0)
        self.assertFalse(view['comparison']['required_coverage_complete'])

    def test_global_limit_is_explicit_and_does_not_change_denominators(self):
        report = compare(*fixture())
        full = select_cases(report, limit=10000)
        limited = select_cases(report, limit=2)
        self.assertEqual(limited['cases'], full['cases'][:2])
        self.assertEqual(limited['selection']['omitted_cases'], len(full['cases']) - 2)
        self.assertTrue(limited['selection']['truncated'])
        self.assertEqual(limited['comparison'], full['comparison'])
        self.assertEqual(sum(s['shown_cases'] for s in limited['slices']), 2)
        self.assertEqual(sum(s['matching_cases'] for s in limited['slices']), len(full['cases']))
        later = next(s for s in limited['slices'] if s['id'] == 'old-camera')
        self.assertGreater(later['matching_cases'], 0)
        self.assertEqual(later['shown_cases'], 0)

    def test_all_transitions_preserve_every_declared_case(self):
        report = compare(*fixture())
        view = select_cases(report, transitions=list(TRANSITIONS), limit=10000)
        self.assertEqual(len(view['cases']), report['observed_totals']['declared_pairs'])

    def test_full_family_inference_never_recomputed_on_displayed_outcomes(self):
        manifest, rows = inferential(100)
        manifest['slices'].append(dict(manifest['slices'][0], id='untested', required=False))
        report = compare(manifest, rows)
        with patch('policydiff.engine.regression_p', side_effect=AssertionError('must not recompute')):
            view = select_cases(report, slice_ids=[report['slices'][0]['id']], transitions=['lost'])
        self.assertEqual(view['comparison']['declared_family_size'], 2)
        self.assertEqual(view['slices'][0]['inference'], report['slices'][0]['inference'])
        self.assertEqual(view['slices'][0]['inference']['per_slice_alpha'], .025)

    def test_projection_does_not_mutate_or_alias_source(self):
        report = compare(*fixture())
        original = deepcopy(report)
        view = select_cases(report)
        view['cases'][0]['records'].clear()
        view['slices'][0]['inference'].clear()
        view['comparison']['limitations'].clear()
        self.assertEqual(report, original)

    def test_invalid_filters_and_limits_fail_not_empty_success(self):
        report = compare(*fixture())
        sid = report['slices'][0]['id']
        for kwargs in ({'slice_ids': ['typo']}, {'slice_ids': [sid, sid]}, {'slice_ids': []},
                       {'slice_ids': sid}, {'transitions': ['typo']}, {'transitions': []},
                       {'transitions': ['lost', 'lost']}, {'limit': 0}, {'limit': True},
                       {'limit': 10001}, {'limit': 2.5}, {'transitions': [None]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EvidenceError):
                select_cases(report, **kwargs)

    def invoke(self, manifest, rows, *options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'm.json').write_bytes(encode(manifest))
            (root / 'e.csv').write_bytes(csv_bytes(rows))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['cases', '--manifest', str(root / 'm.json'), '--episodes', str(root / 'e.csv'), *options])
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['e.csv', 'm.json'])
            return code, out.getvalue(), err.getvalue()

    def test_cli_validates_full_input_before_filtering_and_keeps_hashes(self):
        manifest, rows = fixture()
        sid = manifest['slices'][0]['id']
        code, out, err = self.invoke(manifest, rows, '--slice', sid, '--transition', 'lost')
        self.assertEqual((code, err), (0, ''))
        view = json.loads(out)
        self.assertEqual(view['status'], 'cases_selected')
        self.assertIsNotNone(view['comparison']['inputs'])
        self.assertNotEqual(rows[-1]['slice'], sid)
        rows[-1]['steps'] = 99999  # Rejected even outside the displayed slice.
        code, out, err = self.invoke(manifest, rows, '--slice', sid)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('steps', json.loads(err)['error'])

    def test_strict_coverage_uses_full_population_not_selected_slice(self):
        manifest, rows = fixture()
        code, out, err = self.invoke(manifest, rows, '--slice', manifest['slices'][0]['id'], '--strict-coverage')
        self.assertEqual((code, err), (3, ''))
        self.assertFalse(json.loads(out)['comparison']['required_coverage_complete'])

    def test_cli_typo_and_limit_errors_are_input_rejections(self):
        for options in (('--slice', 'typo'), ('--limit', '0'), ('--limit', '10001')):
            with self.subTest(options=options):
                code, out, err = self.invoke(*fixture(), *options)
                self.assertEqual((code, out), (2, ''))
                self.assertEqual(json.loads(err)['status'], 'invalid_input_or_output')

    def test_cli_maximum_display_limit_and_multiple_filters(self):
        code, out, err = self.invoke(*fixture(), '--limit', '10000', '--slice', 'old-camera',
                                     '--slice', 'old-nominal', '--transition', 'gained', '--transition', 'lost')
        self.assertEqual((code, err), (0, ''))
        view = json.loads(out)
        self.assertEqual(view['selection']['slice_ids'], ['old-nominal', 'old-camera'])
        self.assertEqual(view['selection']['transitions'], ['lost', 'gained'])
        self.assertEqual(view['selection']['shown_cases'], 6)
        self.assertFalse(view['selection']['truncated'])

    def test_closed_output_pipe_reports_completed_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, rows = fixture()
            (root / 'm.json').write_bytes(encode(manifest))
            (root / 'e.csv').write_bytes(csv_bytes(rows))
            command = [sys.executable, '-B', '-m', 'policydiff', 'cases', '--manifest',
                       str(root / 'm.json'), '--episodes', str(root / 'e.csv')]
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                process.stdout.close()
                code = process.wait(timeout=10)
                error = json.loads(process.stderr.read())
            self.assertEqual(code, 2)
            self.assertEqual(error['status'], 'output_notification_failed')
            self.assertEqual(error['command'], 'cases')
            self.assertEqual(error['result_status'], 'cases_selected')
