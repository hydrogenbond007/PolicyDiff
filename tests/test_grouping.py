"""Descriptive groups preserve the declared evidence and inference population."""
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
from policydiff.io import csv_bytes, encode, sha256
from policydiff.report import triage_markdown
from policydiff.triage import GROUP_FIELDS, group_changes
from test_engine import inferential


class GroupingTests(unittest.TestCase):
    def test_groups_expose_losses_hidden_by_gains_with_full_denominators(self):
        view = group_changes(compare(*fixture()))
        group = view['groups'][0]
        self.assertEqual(group['label'], 'pick-known')
        self.assertEqual(group['slice_ids'], ['old-camera', 'old-nominal'])
        self.assertEqual((group['transitions']['lost'], group['transitions']['gained']), (5, 1))
        self.assertEqual((group['paired_outcomes'], group['declared_pairs']), (24, 24))
        self.assertEqual(group['unchanged_retest'],
                         {'pairs': 24, 'declared_pairs': 24, 'churn_losses': 1, 'churn_gains': 0})
        self.assertEqual(group['revisions']['before']['successes'], 20)
        self.assertEqual(group['revisions']['after']['successes'], 16)

    def test_each_grouping_preserves_population_and_does_not_deduplicate_case_ids(self):
        report = compare(*fixture())
        for field in GROUP_FIELDS:
            with self.subTest(field=field):
                view = group_changes(report, group_by=field)
                self.assertEqual(sum(group['declared_pairs'] for group in view['groups']), 72)
                for transition in ('lost', 'gained', 'unresolved'):
                    self.assertEqual(sum(group['transitions'][transition] for group in view['groups']),
                                     report['observed_totals'][transition])
                for group in view['groups']:
                    self.assertEqual(sum(group['transitions'].values()), group['declared_pairs'])
                    self.assertEqual(group['paired_outcomes'], group['declared_pairs'] - group['transitions']['unresolved'])
                self.assertEqual(sorted(sid for group in view['groups'] for sid in group['slice_ids']),
                                 sorted(slice_report['id'] for slice_report in report['slices']))

    def test_rank_missing_evidence_and_keep_interruption_distinct_from_failure(self):
        view = group_changes(compare(*fixture()), rank_by='unresolved')
        future, interrupted = view['groups'][:2]
        self.assertEqual((future['label'], future['paired_outcomes'], future['transitions']['unresolved']),
                         ('future-task', 0, 12))
        self.assertEqual(future['revisions']['after']['missing_records'], 12)
        self.assertEqual(future['coverage_counts']['not_tested'], 1)
        self.assertEqual(future['unchanged_retest']['pairs'], 0)
        self.assertEqual(interrupted['label'], 'old-other')
        self.assertEqual(interrupted['revisions']['after']['terminal_status_counts']['interrupted'], 1)
        self.assertEqual(interrupted['revisions']['after']['scored_outcomes'], 11)
        self.assertEqual(interrupted['transitions']['unresolved'], 1)
        self.assertFalse(interrupted['required_coverage_complete'])
        rendered = triage_markdown(view)
        self.assertIn('not measured (0/12 pairs)', rendered)
        self.assertIn('| old\\-other | 1 | 0 | 0 | 0 / 1 | incomplete (1 slices) |', rendered)
        self.assertIn('| pick\\-known | 0 | 0 | 0 | 0 / 2 | complete (2 slices) |', rendered)

    def test_retest_pairs_do_not_depend_on_candidate_coverage(self):
        manifest, rows = fixture()
        rows = [row for row in rows if row['revision'] != 'after']
        group = next(group for group in group_changes(compare(manifest, rows))['groups']
                     if group['label'] == 'pick-known')
        self.assertEqual(group['paired_outcomes'], 0)
        self.assertEqual(group['unchanged_retest']['pairs'], 24)
        self.assertEqual(group['transitions']['unresolved'], 24)
        self.assertEqual(group['revisions']['after']['successes'], 0)
        self.assertEqual(group['revisions']['after']['scored_outcomes'], 0)

    def test_absent_retest_remains_absent(self):
        manifest, rows = fixture()
        manifest.pop('retest')
        rows = [row for row in rows if row['revision'] != 'retest']
        view = group_changes(compare(manifest, rows))
        self.assertTrue(all(group['unchanged_retest'] is None for group in view['groups']))
        self.assertIn('not supplied', triage_markdown(view))

    def test_same_condition_label_on_different_axes_stays_separate(self):
        manifest, rows = fixture()
        manifest['slices'][0]['condition'] = 'high'
        manifest['slices'][1]['condition'] = 'high'
        view = group_changes(compare(manifest, rows), group_by='condition')
        groups = [group for group in view['groups'] if group['dimensions']['condition'] == 'high']
        self.assertEqual(len(groups), 2)
        self.assertEqual({group['dimensions']['axis'] for group in groups}, {'nominal', 'camera'})
        self.assertTrue(all(len(group['slice_ids']) == 1 for group in groups))

    def test_missingness_partition_remains_visible_in_json_and_markdown(self):
        manifest, rows = inferential(3)
        absent = {('after', '0'), ('before', '1'), ('before', '2'), ('after', '2')}
        rows = [row for row in rows if (row['revision'], row['case']) not in absent]
        view = group_changes(compare(manifest, rows), rank_by='unresolved')
        group = view['groups'][0]
        self.assertEqual(group['outcome_coverage'], {'both_outcomes': 0, 'baseline_only_outcome': 1,
                         'candidate_only_outcome': 1, 'neither_outcome': 1})
        self.assertEqual(group['transitions']['unresolved'], 3)
        self.assertEqual(group['eligible_slice_count'], 0)
        self.assertIn('incomplete or untested declared comparison population', group['ineligible_reason_counts'])
        self.assertIn('Baseline outcome only', triage_markdown(view))

    def test_partially_measured_retest_preserves_its_observed_pairs(self):
        manifest, rows = fixture()
        rows = [row for row in rows if not (row['slice'] == 'old-camera' and row['revision'] == 'retest')]
        view = group_changes(compare(manifest, rows))
        group = view['groups'][0]
        self.assertEqual(group['unchanged_retest'],
                         {'pairs': 12, 'declared_pairs': 24, 'churn_losses': 1, 'churn_gains': 0})
        self.assertEqual(group['revisions']['retest']['missing_records'], 12)
        self.assertFalse(group['required_coverage_complete'])
        self.assertIn('(12/24 pairs)', triage_markdown(view))

    def test_optional_untested_group_is_visible_with_zero_required_slices(self):
        manifest, _ = fixture()
        view = group_changes(compare(manifest, []))
        self.assertEqual(len(view['groups']), 5)
        optional = next(group for group in view['groups'] if group['label'] == 'future-task')
        self.assertEqual(optional['required_slice_count'], 0)
        self.assertEqual(optional['transitions']['unresolved'], 12)
        self.assertEqual(optional['eligible_slice_count'], 0)
        self.assertFalse(view['comparison']['required_coverage_complete'])
        rendered = triage_markdown(view)
        self.assertIn('(5 required slices)', rendered)
        self.assertIn('| future\\-task | 0 | 0 | 12 | 0 / 1 | not required (0 slices) |', rendered)
        self.assertIn('| Required | Coverage |', rendered)
        self.assertIn('| no | not\\_tested |', rendered)
        self.assertIn('| yes | not\\_tested |', rendered)

    def test_group_order_is_deterministic_under_slice_and_row_permutation(self):
        manifest, rows = fixture()
        expected = group_changes(compare(manifest, rows))
        manifest['slices'].reverse()
        observed = group_changes(compare(manifest, list(reversed(rows))))
        self.assertEqual(expected['groups'], observed['groups'])
        self.assertEqual(expected['ranking'], observed['ranking'])
        self.assertEqual([group['label'] for group in expected['groups'][1:]],
                         sorted(group['label'] for group in expected['groups'][1:]))

    def test_grouping_preserves_original_inference_without_pooling_or_mutation(self):
        manifest, rows = inferential(20)
        manifest['slices'].append(dict(manifest['slices'][0], id='untested', required=False))
        report = compare(manifest, rows)
        original = deepcopy(report)
        with patch('policydiff.engine.regression_p', side_effect=AssertionError('no regrouped inference')):
            view = group_changes(report)
        self.assertEqual(view['comparison']['declared_family_size'], 2)
        self.assertEqual(view['slices'][0]['inference'], report['slices'][0]['inference'])
        self.assertNotIn('inference', view['groups'][0])
        view['slices'][0]['inference'].clear()
        view['comparison']['limitations'].clear()
        view['groups'][0]['revisions'].clear()
        self.assertEqual(report, original)

    def test_unknown_grouping_and_ranking_reject_instead_of_silently_omitting(self):
        report = compare(*fixture())
        for options in ({'group_by': 'typo'}, {'rank_by': 'gains'}, {'group_by': None}, {'rank_by': []}):
            with self.subTest(options=options), self.assertRaises(EvidenceError):
                group_changes(report, **options)

    def test_markdown_escapes_labels_and_explains_rank_scope(self):
        manifest, rows = fixture()
        manifest['title'] = '<script>alert(1)</script>'
        manifest['slices'][0]['condition'] = '[click](https://example.org)|<img src=x>'
        view = group_changes(compare(manifest, rows), group_by='condition')
        rendered = triage_markdown(view)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img', rendered)
        self.assertNotIn('[click](', rendered)
        self.assertIn('\\|', rendered)
        self.assertIn('slice-cases', rendered)
        self.assertIn('not severity', rendered)
        self.assertIn('synthetic', rendered)
        self.assertIn('Original slices', rendered)

    def invoke(self, manifest, rows, *options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_bytes(encode(manifest))
            (root / 'episodes.csv').write_bytes(csv_bytes(rows))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['triage', '--manifest', str(root / 'manifest.json'),
                             '--episodes', str(root / 'episodes.csv'), *options])
            self.assertEqual(sorted(path.name for path in root.iterdir()), ['episodes.csv', 'manifest.json'])
            return code, out.getvalue(), err.getvalue()

    def test_cli_keeps_exact_hashes_and_strict_coverage_in_both_formats(self):
        manifest, rows = fixture()
        code, out, err = self.invoke(manifest, rows, '--strict-coverage')
        self.assertEqual((code, err), (3, ''))
        view = json.loads(out)
        self.assertEqual(view['status'], 'changes_grouped')
        self.assertEqual(view['comparison']['inputs'],
                         {'manifest_sha256': sha256(encode(manifest)), 'episodes_sha256': sha256(csv_bytes(rows))})
        code, out, err = self.invoke(manifest, rows, '--strict-coverage', '--format', 'markdown')
        self.assertEqual((code, err), (3, ''))
        self.assertIn('Required coverage complete: False', out)

    def test_cli_validates_all_records_before_grouping(self):
        manifest, rows = fixture()
        rows[-1]['steps'] = 99999
        code, out, err = self.invoke(manifest, rows)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('steps', json.loads(err)['error'])

    def test_closed_pipe_retains_successful_triage_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, rows = fixture()
            (root / 'manifest.json').write_bytes(encode(manifest))
            (root / 'episodes.csv').write_bytes(csv_bytes(rows))
            command = [sys.executable, '-B', '-m', 'policydiff', 'triage', '--manifest',
                       str(root / 'manifest.json'), '--episodes', str(root / 'episodes.csv')]
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                process.stdout.close()
                code = process.wait(timeout=10)
                error = json.loads(process.stderr.read())
            self.assertEqual(code, 2)
            self.assertEqual(error['status'], 'output_notification_failed')
            self.assertEqual(error['result_status'], 'changes_grouped')
