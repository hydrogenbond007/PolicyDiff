import copy
import unittest

from policydiff import EvidenceError, compare
from policydiff.demo import digest, fixture
from policydiff.schema import validate_manifest


def single(n=12):
    manifest, rows = fixture(n)
    manifest['slices'] = manifest['slices'][:1]
    return manifest, [r for r in rows if r['slice'] == 'old-nominal']


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.rows = single()

    def test_valid_fixture(self):
        self.assertTrue(compare(self.manifest, self.rows)['input_valid'])

    def test_case_membership_is_indexed_without_changing_declared_order(self):
        class NoLinearScan(list):
            def __contains__(self, item):
                raise AssertionError('per-row case membership must use the index')

        expected = compare(self.manifest, self.rows)
        sl = self.manifest['slices'][0]
        sl['case_ids'] = NoLinearScan(sl['case_ids'])
        self.assertEqual(compare(self.manifest, self.rows), expected)
        self.rows[0]['case'] = 'undeclared'
        with self.assertRaisesRegex(EvidenceError, 'undeclared case ID'):
            compare(self.manifest, self.rows)

    def test_fixture_is_valid_at_size_boundaries(self):
        for n in (1, 2, 71, 72, 1000):
            with self.subTest(n=n):
                self.assertTrue(compare(*fixture(n))['input_valid'])

    def test_fixture_rejects_invalid_sizes(self):
        for n in (0, -1, 1001, True, 1.5):
            with self.subTest(n=n), self.assertRaises(EvidenceError):
                fixture(n)

    def test_nonobject_rows_and_nonlist_input_rejected(self):
        for rows in ([None], ['x'], [False], (), None):
            with self.subTest(rows=rows), self.assertRaises(EvidenceError):
                compare(self.manifest, rows)

    def test_schema_size_limits(self):
        m = copy.deepcopy(self.manifest)
        m['slices'] *= 101
        with self.assertRaises(EvidenceError):
            compare(m, [])
        m = copy.deepcopy(self.manifest)
        m['slices'][0]['case_ids'] = [str(i) for i in range(1001)]
        with self.assertRaises(EvidenceError):
            compare(m, [])
        m, _ = single(1000)
        m['slices'] = [dict(m['slices'][0], id=f's{i}') for i in range(11)]
        with self.assertRaisesRegex(EvidenceError, '10000'):
            compare(m, [])
        with self.assertRaisesRegex(EvidenceError, 'too many rows'):
            compare(self.manifest, self.rows + [copy.deepcopy(self.rows[0])])

    def test_physical_aliases_allowed_across_different_slices(self):
        m, rows = fixture()
        a, b = m['slices'][:2]
        m['slices'] = [a, b]
        rows = [r for r in rows if r['slice'] in (a['id'], b['id'])]
        for row in rows:
            row['physical_state_sha256'] = digest('same-across-slices-' + row['case'])
        self.assertTrue(compare(m, rows)['input_valid'])

    def test_library_report_has_version_and_provenance_shape(self):
        from policydiff import __version__
        report = compare(self.manifest, self.rows)
        self.assertEqual(report['report_schema_version'], 1)
        self.assertEqual(report['input_schema_version'], 1)
        self.assertEqual(report['producer']['version'], __version__)
        self.assertIsNone(report['inputs'])

    def test_inputs_not_mutated(self):
        original = copy.deepcopy((self.manifest, self.rows))
        compare(self.manifest, self.rows)
        self.assertEqual(original, (self.manifest, self.rows))

    def test_report_manifest_not_aliased_to_callers_mutable_data(self):
        report = compare(self.manifest, self.rows)
        self.manifest['title'] = 'changed after comparison'
        self.assertNotEqual(report['manifest']['title'], self.manifest['title'])

    def test_falsey_nonobjects_rejected(self):
        for bad in (None, [], '', False, 0):
            with self.subTest(bad=bad), self.assertRaises(EvidenceError):
                validate_manifest(bad)
        for key in ('baseline', 'candidate', 'sampling', 'change'):
            for bad in (None, [], '', False, 0):
                m = copy.deepcopy(self.manifest)
                m[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(EvidenceError):
                    compare(m, self.rows)

    def test_unknown_fields_rejected(self):
        self.manifest['secret_extension'] = True
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_family_mismatch_rejected(self):
        self.manifest['candidate']['family'] = 'another-family'
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_wrong_parent_rejected(self):
        self.manifest['candidate']['parent'] = 'unrelated'
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_retest_checkpoint_mismatch_rejected(self):
        self.manifest['retest']['checkpoint_sha256'] = digest('different')
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_weights_require_different_bytes(self):
        self.manifest['candidate']['checkpoint_sha256'] = self.manifest['baseline']['checkpoint_sha256']
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_context_change_not_weight_update(self):
        self.manifest['change']['kind'] = 'context'
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)
        self.manifest['candidate']['checkpoint_sha256'] = self.manifest['baseline']['checkpoint_sha256']
        for row in self.rows:
            row['checkpoint_sha256'] = self.manifest['baseline']['checkpoint_sha256']
        self.assertEqual(compare(self.manifest, self.rows)['change_kind'], 'context')

    def test_hardware_rejected(self):
        self.manifest['evidence_origin'] = 'hardware'
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_boolean_number_confusion_rejected(self):
        for path in ('schema_version', 'horizon_steps', 'alpha'):
            m = copy.deepcopy(self.manifest)
            if path == 'schema_version':
                m[path] = True
            elif path == 'alpha':
                m['sampling'][path] = True
            else:
                m['slices'][0][path] = True
            with self.subTest(path=path), self.assertRaises(EvidenceError):
                compare(m, self.rows)

    def test_probability_and_metric_nonfinite_rejected(self):
        for value in (float('nan'), float('inf'), -1, 0, 1, 10 ** 1000):
            m = copy.deepcopy(self.manifest)
            m['sampling']['alpha'] = value
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                compare(m, self.rows)
        for value in ('nan', 'inf', '-1', True):
            rows = copy.deepcopy(self.rows)
            rows[0]['wall_seconds'] = value
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                compare(self.manifest, rows)

    def test_multiplicity_alpha_underflow_rejected(self):
        m, rows = fixture()
        m['sampling']['alpha'] = 5e-324
        with self.assertRaises(EvidenceError):
            compare(m, rows)

    def test_duplicate_revision_or_case_ids(self):
        self.manifest['candidate']['id'] = 'before'
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)
        self.manifest, self.rows = single()
        self.manifest['slices'][0]['case_ids'].append('0')
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_duplicate_episode_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_unknown_case_rejected(self):
        self.rows[0]['case'] = 'not-planned'
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_identity_mismatches_rejected(self):
        for key in ('checkpoint_sha256', 'contract_sha256', 'physical_state_sha256', 'rng_sha256'):
            rows = copy.deepcopy(self.rows)
            rows[0][key] = digest('wrong')
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                compare(self.manifest, rows)

    def test_different_slice_contracts_allowed(self):
        m, rows = fixture()
        self.assertNotEqual(m['slices'][0]['contract_sha256'], m['slices'][1]['contract_sha256'])
        self.assertTrue(compare(m, rows)['input_valid'])

    def test_repeated_physical_start_rejected(self):
        for row in self.rows:
            if row['case'] == '1':
                row['physical_state_sha256'] = digest('old-nominal/physical/0')
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_alias_in_candidate_only_outcomes_rejected(self):
        self.rows = [r for r in self.rows if r['revision'] == 'after']
        for row in self.rows:
            row['physical_state_sha256'] = digest('alias')
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_retest_churn_preserved_not_rejected(self):
        sl = compare(self.manifest, self.rows)['slices'][0]
        self.assertEqual(sl['unchanged_retest']['churn_losses'], 1)
        self.assertEqual(sl['observed_pairs']['harmful_flips'], 1)
        self.assertEqual(set(sl['unchanged_retest']), {
            'arm', 'pairs', 'declared_pairs', 'coverage', 'baseline_successes',
            'retest_successes', 'churn_losses', 'churn_gains', 'discordant_pairs'})
        self.assertEqual(sl['unchanged_retest']['arm'], 'retest')

    def test_unscored_physical_alias_rejected(self):
        for row in self.rows:
            if row['case'] == '1':
                row.update(status='interrupted', success='', physical_state_sha256=digest('old-nominal/physical/0'))
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_infrastructure_cannot_carry_score(self):
        for status in ('infrastructure_error', 'interrupted'):
            for score in (True, False, '0', '1'):
                rows = copy.deepcopy(self.rows)
                rows[0].update(status=status, success=score)
                with self.subTest(status=status, score=score), self.assertRaises(EvidenceError):
                    compare(self.manifest, rows)

    def test_policy_failure_is_failure(self):
        self.rows[0].update(status='policy_failure', success=False)
        sl = compare(self.manifest, self.rows)['slices'][0]
        self.assertEqual(sl['revisions']['before']['successes'], 9)
        self.assertEqual(sl['revisions']['before']['scored_outcomes'], 12)
        self.rows[0]['success'] = True
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_ambiguous_outcomes_rejected(self):
        for value in ('', None, 1, 0, 'yes', 'TRUE'):
            rows = copy.deepcopy(self.rows)
            rows[0]['success'] = value
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                compare(self.manifest, rows)

    def test_horizon_violation_rejected(self):
        self.rows[0]['steps'] = 101
        with self.assertRaises(EvidenceError):
            compare(self.manifest, self.rows)

    def test_evidence_reference_paths_rejected(self):
        for value in ('/etc/passwd', '../secret', 'a/../../secret', 'https://example.org', 'C:\\secret', 'a\nsecret'):
            rows = copy.deepcopy(self.rows)
            rows[0]['evidence_ref'] = value
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                compare(self.manifest, rows)

    def test_exposure_contradictions_rejected(self):
        for role, parent, update in (('old_rehearsed', 'unknown', 'included'),
                                     ('old_unrehearsed', 'included', 'included'),
                                     ('adaptation_target', 'excluded', 'excluded'),
                                     ('held_out', 'included', 'excluded'),
                                     ('held_out', 'excluded', 'unknown')):
            m = copy.deepcopy(self.manifest)
            m['slices'][0].update(role=role, parent_exposure=parent, update_exposure=update)
            with self.subTest(role=role, parent=parent, update=update), self.assertRaises(EvidenceError):
                compare(m, self.rows)


if __name__ == '__main__':
    unittest.main()
