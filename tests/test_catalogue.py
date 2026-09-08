"""Task metadata tests do not execute any simulator or establish policy competence."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from policydiff import EvidenceError, list_tasks
from policydiff.catalogue import resolve_task
from policydiff.cli import main


class CatalogueTests(unittest.TestCase):
    def test_complete_pinned_catalogue_and_explicit_non_readiness(self):
        result = list_tasks()
        self.assertEqual(result['catalogue_task_count'], 130)
        self.assertEqual(result['selected_task_count'], 130)
        self.assertEqual(len({task['id'] for task in result['tasks']}), 130)
        self.assertEqual({s['id']: s['task_count'] for s in result['suites']},
                         {'libero_spatial': 10, 'libero_object': 10, 'libero_goal': 10,
                          'libero_10': 10, 'libero_90': 90})
        for task in result['tasks']:
            self.assertEqual(resolve_task(task['id']), task)
            self.assertEqual(task['availability'], 'listed')
            self.assertEqual(task['policy_compatibility'], 'not_established')
            self.assertEqual(task['training_exposure'], 'not_assessed')

    def test_filtering_retains_catalogue_size_and_source_order(self):
        result = list_tasks(suite='libero_object', query='JUICE')
        self.assertEqual(result['catalogue_task_count'], 130)
        self.assertEqual(result['selected_task_count'], 1)
        self.assertEqual(result['tasks'][0]['id'], 'libero_object.9')
        self.assertEqual(list_tasks(query='no matching task')['tasks'], [])

    def test_returned_records_do_not_mutate_catalogue(self):
        original = list_tasks()
        result = list_tasks()
        result['tasks'][0]['name'] = 'changed'
        result['suites'][0]['task_count'] = 0
        self.assertEqual(list_tasks(), original)

    def test_bad_selections_fail_closed(self):
        for suite in ('unknown', [], 3, True):
            with self.subTest(suite=suite), self.assertRaises(EvidenceError):
                list_tasks(suite=suite)
        for query in ('', ' ', '\x1b', 'a' * 201, [], 0):
            with self.subTest(query=query), self.assertRaises(EvidenceError):
                list_tasks(query=query)
        for task in ('libero_object.99', 'libero_object.09', '../anything', '', None):
            with self.subTest(task=task), self.assertRaises(EvidenceError):
                resolve_task(task)

    def test_cli_is_offline_and_does_not_read_a_checkpoint(self):
        out, err = io.StringIO(), io.StringIO()
        with patch('policydiff.cli.read_snapshot', side_effect=AssertionError('unexpected input read')):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['catalog', '--suite', 'libero_goal'])
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(json.loads(out.getvalue())['selected_task_count'], 10)
