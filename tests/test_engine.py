import copy
import itertools
import math
import unittest

from policydiff import compare
from policydiff.demo import fixture
from policydiff.statistics import harmful_flip_upper_bound, regression_p
from test_contract import single


def inferential(n=100):
    m, rows = single(n)
    # Test-only declared metadata to exercise mathematical branches, not real data.
    m['evidence_origin'] = 'simulation'
    m['sampling'].update(design='iid_pairs', frozen_before_outcomes=True)
    for row in rows:
        row['success'] = True
        row['steps'] = 40
    return m, rows


class EngineTests(unittest.TestCase):
    def test_every_terminal_state_combination_preserves_missingness(self):
        m, template = single(1)
        states = (None, ('completed', True), ('completed', False),
                  ('policy_failure', False), ('infrastructure_error', None),
                  ('interrupted', None))
        for combination in itertools.product(states, repeat=3):
            with self.subTest(states=combination):
                rows = [dict(row, status=state[0], success=state[1])
                        for row, state in zip(template, combination) if state]
                report = compare(m, rows)
                sl = report['slices'][0]
                before, after = combination[:2]
                scored = [state is not None and state[1] is not None for state in combination]
                paired = scored[0] and scored[1]
                loss = paired and before[1] and not after[1]
                gain = paired and not before[1] and after[1]
                transition = ('unresolved' if not paired else 'lost' if loss else 'gained'
                              if gain else 'retained_success' if before[1] else 'shared_failure')
                self.assertEqual(sl['cases'][0]['transition'], transition)
                self.assertEqual(sl['observed_pairs']['pairs'], int(paired))
                self.assertEqual(sl['observed_pairs']['harmful_flips'], int(loss))
                self.assertEqual(sl['observed_pairs']['helpful_flips'], int(gain))
                self.assertEqual(report['observed_totals']['unresolved'], int(not paired))
                self.assertEqual(report['required_coverage_complete'], all(scored))
                self.assertEqual(sl['coverage'], 'complete' if all(scored) else
                                 'incomplete' if rows else 'not_tested')
                self.assertEqual(sl['unchanged_retest']['pairs'], int(scored[0] and scored[2]))
                self.assertIsNone(report['has_inferential_regression'])

    def test_input_row_order_does_not_change_report(self):
        m, rows = fixture()
        self.assertEqual(compare(m, rows), compare(m, list(reversed(rows))))

    def test_report_nested_data_is_detached_from_inputs(self):
        m, rows = single()
        original = copy.deepcopy((m, rows))
        report = compare(m, rows)
        report['manifest']['slices'][0]['case_ids'].append('report-only')
        report['slices'][0]['cases'][0]['records']['before']['success'] = False
        report['slices'][0]['revisions']['before']['missing_cases'].append('report-only')
        self.assertEqual((m, rows), original)
        before = copy.deepcopy(compare(m, rows))
        after = compare(m, rows)
        m['slices'][0]['case_ids'].clear()
        rows[0]['success'] = not rows[0]['success']
        self.assertEqual(after, before)

    def test_slices_with_shared_case_ids_remain_independent_and_ordered(self):
        m, rows = inferential(12)
        second = dict(m['slices'][0], id='same-starts-other-condition', required=False)
        m['slices'].append(second)
        rows += [dict(row, slice=second['id'], success=row['revision'] != 'after')
                 for row in rows[:]]
        report = compare(m, rows)
        first, second_report = report['slices']
        self.assertEqual(first['observed_pairs']['harmful_flips'], 0)
        self.assertEqual(second_report['observed_pairs']['harmful_flips'], 12)
        self.assertTrue(report['required_coverage_complete'])
        self.assertTrue(report['has_inferential_regression'])
        self.assertEqual(report['observed_totals']['lost'], 12)
        self.assertEqual(report['eligible_slice_count'], 2)
        m['slices'].reverse()
        for sl in m['slices']:
            sl['case_ids'] = list(reversed(sl['case_ids']))
        reversed_report = compare(m, list(reversed(rows)))
        self.assertEqual([sl['id'] for sl in reversed_report['slices']],
                         [sl['id'] for sl in m['slices']])
        for old, new in zip(report['slices'], reversed(reversed_report['slices'])):
            self.assertEqual(old['cases'], list(reversed(new['cases'])))
            self.assertEqual({k: v for k, v in old.items() if k != 'cases'},
                             {k: v for k, v in new.items() if k != 'cases'})
        for key in ('coverage_counts', 'observed_totals', 'eligible_slice_count',
                    'has_inferential_regression', 'required_coverage_complete'):
            self.assertEqual(report[key], reversed_report[key])

    def test_swapping_recorded_outcomes_reverses_flips_and_asymmetric_coverage(self):
        m, rows = single()
        rows = [row for row in rows if (row['revision'], row['case']) != ('after', '0')]
        forward = compare(m, rows)['slices'][0]
        swapped = []
        for row in rows:
            row = dict(row)
            if row['revision'] != 'retest':
                row['revision'] = 'after' if row['revision'] == 'before' else 'before'
                revision = 'candidate' if row['revision'] == 'after' else 'baseline'
                row['checkpoint_sha256'] = m[revision]['checkpoint_sha256']
            swapped.append(row)
        reverse = compare(m, swapped)['slices'][0]
        a, b = forward['observed_pairs'], reverse['observed_pairs']
        self.assertEqual((a['harmful_flips'], a['helpful_flips']),
                         (b['helpful_flips'], b['harmful_flips']))
        self.assertEqual(a['net_success_change'], -b['net_success_change'])
        self.assertEqual(a['pairs'], b['pairs'])
        self.assertEqual(forward['outcome_coverage']['baseline_only_outcome'],
                         reverse['outcome_coverage']['candidate_only_outcome'])
        self.assertEqual(forward['coverage'], reverse['coverage'])

    def test_unchanged_average_can_hide_flips(self):
        m, rows = single()
        p = compare(m, rows)['slices'][0]['observed_pairs']
        self.assertEqual((p['baseline_successes'], p['candidate_successes']), (10, 10))
        self.assertEqual((p['harmful_flips'], p['helpful_flips'], p['net_success_change']), (1, 1, 0))
        self.assertEqual((p['pairs'], p['declared_pairs'], p['discordant_pairs']), (12, 12, 2))

    def test_unmeasured_conditions_never_disappear(self):
        m, rows = fixture()
        report = compare(m, rows)
        sl = report['slices'][-1]
        self.assertEqual(sl['coverage'], 'not_tested')
        self.assertEqual(sl['observed_pairs']['pairs'], 0)
        self.assertEqual(len(sl['revisions']['before']['missing_cases']), 12)
        self.assertEqual(len(report['slices']), len(m['slices']))

    def test_empty_required_slice_visible_incomplete(self):
        m, _ = single()
        report = compare(m, [])
        self.assertFalse(report['required_coverage_complete'])
        self.assertEqual(report['slices'][0]['coverage'], 'not_tested')
        self.assertFalse(report['slices'][0]['inference']['eligible'])

    def test_synthetic_cannot_gain_inference_via_sampling_flags(self):
        m, rows = inferential()
        m['evidence_origin'] = 'synthetic'
        sl = compare(m, rows)['slices'][0]
        self.assertEqual(sl['inference']['status'], 'descriptive_only')
        self.assertIsNone(sl['inference']['regression_p'])

    def test_summary_reports_losses_when_no_slice_eligible(self):
        m, rows = fixture()
        report = compare(m, rows)
        self.assertGreater(report['observed_totals']['lost'], 0)
        self.assertEqual(report['eligible_slice_count'], 0)
        self.assertIsNone(report['has_inferential_regression'])

    def test_inference_carries_retest_churn_context(self):
        m, rows = inferential()
        next(r for r in rows if r['revision'] == 'retest')['success'] = False
        inf = compare(m, rows)['slices'][0]['inference']
        self.assertTrue(inf['eligible'])
        self.assertEqual(inf['unchanged_retest_discordant_pairs'], 1)
        self.assertIn('not subtracted', inf['churn_caveat'])

    def test_missingness_does_not_create_preservation(self):
        m, rows = inferential()
        rows = [r for r in rows if not (r['revision'] == 'after' and r['case'] == '0')]
        sl = compare(m, rows)['slices'][0]
        self.assertEqual(sl['observed_pairs']['pairs'], 99)
        self.assertEqual(sl['observed_pairs']['declared_pairs'], 100)
        self.assertEqual(sl['outcome_coverage'], {'both_outcomes': 99, 'baseline_only_outcome': 1,
                                                'candidate_only_outcome': 0, 'neither_outcome': 0})
        self.assertEqual(sl['inference']['status'], 'descriptive_only')

    def test_crash_to_win_cannot_hide_population(self):
        m, rows = inferential()
        for r in rows:
            if r['revision'] == 'after' and int(r['case']) < 40:
                r.update(status='infrastructure_error', success='')
        sl = compare(m, rows)['slices'][0]
        self.assertEqual(sl['observed_pairs']['candidate_successes'], 60)
        self.assertEqual(sl['observed_pairs']['declared_pairs'], 100)
        self.assertEqual(sl['revisions']['after']['terminal_status_counts']['infrastructure_error'], 40)
        self.assertEqual(sl['outcome_coverage']['baseline_only_outcome'], 40)
        self.assertFalse(sl['inference']['eligible'])

    def test_all_asymmetric_coverage_categories(self):
        m, rows = single()
        rows = [r for r in rows if not ((r['case'] == '0' and r['revision'] == 'after')
                                        or (r['case'] == '1' and r['revision'] == 'before')
                                        or (r['case'] == '2' and r['revision'] in ('before', 'after')))]
        self.assertEqual(compare(m, rows)['slices'][0]['outcome_coverage'],
                         {'both_outcomes': 9, 'baseline_only_outcome': 1,
                          'candidate_only_outcome': 1, 'neither_outcome': 1})

    def test_incomplete_retest_blocks_inference(self):
        m, rows = inferential()
        rows = [r for r in rows if not (r['revision'] == 'retest' and r['case'] == '0')]
        self.assertFalse(compare(m, rows)['slices'][0]['inference']['eligible'])

    def test_complete_retest_arm_with_gapped_comparison_partner(self):
        for missing_arm in ('before', 'after'):
            with self.subTest(missing_arm=missing_arm):
                m, rows = inferential()
                rows = [r for r in rows if not (r['revision'] == missing_arm and r['case'] == '0')]
                sl = compare(m, rows)['slices'][0]
                self.assertEqual(sl['revisions']['retest']['scored_outcomes'], 100)
                self.assertEqual(sl['coverage'], 'incomplete')
                self.assertFalse(sl['inference']['eligible'])
                retest_complete = missing_arm == 'after'
                self.assertEqual(sl['unchanged_retest']['pairs'], 100 if retest_complete else 99)
                self.assertEqual(sl['unchanged_retest']['coverage'], 'complete' if retest_complete else 'incomplete')
                self.assertEqual(sl['inference']['unchanged_retest_discordant_pairs'], 0 if retest_complete else None)

    def test_missing_and_partial_retests_not_measured_stability(self):
        for cases in ([], ['0']):
            m, rows = inferential()
            rows = [r for r in rows if r['revision'] != 'retest' or r['case'] in cases]
            sl = compare(m, rows)['slices'][0]
            self.assertEqual(sl['unchanged_retest']['coverage'], 'incomplete' if cases else 'not_tested')
            self.assertIsNone(sl['inference']['unchanged_retest_discordant_pairs'])
            self.assertEqual(sl['unchanged_retest']['pairs'], len(cases))

    def test_zero_count_categories_are_stable(self):
        m, rows = single()
        report = compare(m, rows)
        self.assertEqual(report['coverage_counts'], {'complete': 1, 'incomplete': 0, 'not_tested': 0})
        self.assertEqual(report['slices'][0]['revisions']['before']['terminal_status_counts'],
                         {'completed': 12, 'policy_failure': 0, 'infrastructure_error': 0, 'interrupted': 0})

    def test_optional_retest_absent_still_descriptive(self):
        m, rows = inferential()
        del m['retest']
        rows = [r for r in rows if r['revision'] != 'retest']
        report = compare(m, rows)
        self.assertTrue(report['required_coverage_complete'])
        self.assertIsNone(report['slices'][0]['unchanged_retest'])
        self.assertFalse(report['slices'][0]['inference']['eligible'])

    def test_baseline_competence_gate(self):
        m, rows = inferential()
        for r in rows:
            r['success'] = int(r['case']) < 10
        inf = compare(m, rows)['slices'][0]['inference']
        self.assertFalse(inf['eligible'])
        self.assertIn('baseline is below the caller-declared competence threshold', inf['ineligible_reasons'])

    def test_no_baseline_success_no_retention_claim(self):
        m, rows = inferential()
        for r in rows:
            r['success'] = False
        self.assertFalse(compare(m, rows)['slices'][0]['inference']['eligible'])

    def test_zero_flips_small_sample_inconclusive(self):
        m, rows = inferential(12)
        self.assertEqual(compare(m, rows)['slices'][0]['inference']['status'], 'inconclusive')

    def test_bound_only_with_eligible_and_sufficient_evidence(self):
        m, rows = inferential(100)
        inf = compare(m, rows)['slices'][0]['inference']
        self.assertEqual(inf['status'], 'within_declared_harm_bound')
        self.assertAlmostEqual(inf['harmful_flip_probability_upper_bound'], 1 - .05 ** .01)

    def test_regression_branch(self):
        m, rows = inferential(12)
        for r in rows:
            if r['revision'] == 'after':
                r['success'] = False
        report = compare(m, rows)
        self.assertTrue(report['has_inferential_regression'])
        self.assertEqual(report['slices'][0]['inference']['status'], 'regression_detected')

    def test_all_declared_slices_count_for_multiplicity(self):
        m, rows = inferential()
        new = copy.deepcopy(m['slices'][0])
        new.update(id='untested-extra', required=False)
        m['slices'].append(new)
        report = compare(m, rows)
        self.assertEqual(report['declared_family_size'], 2)
        self.assertEqual(report['slices'][0]['inference']['per_slice_alpha'], .025)

    def test_unknown_parent_exposure_is_not_novelty(self):
        m, rows = fixture()
        report = compare(m, rows)
        held = next(s for s in report['slices'] if s['id'] == 'held-out')
        self.assertEqual(held['exposure_status'], 'parent_exposure_unknown')
        self.assertEqual(held['inference']['status'], 'descriptive_only')

    def test_held_out_not_formal_retention(self):
        m, rows = inferential()
        m['slices'][0].update(role='held_out', parent_exposure='excluded', update_exposure='excluded')
        self.assertFalse(compare(m, rows)['slices'][0]['inference']['eligible'])

    def test_fixed_or_posthoc_sampling_withholds_inference(self):
        for setting in ({'design': 'fixed_cases'}, {'frozen_before_outcomes': False}):
            m, rows = inferential()
            m['sampling'].update(setting)
            self.assertFalse(compare(m, rows)['slices'][0]['inference']['eligible'])

    def test_metrics_use_only_available_paired_values(self):
        m, rows = single()
        rows[0]['steps'] = ''
        metric = compare(m, rows)['slices'][0]['metrics']['steps']
        self.assertEqual(metric['paired_values'], 11)
        self.assertEqual(metric['paired_outcomes'], 12)
        self.assertIn('censoring', metric['scope'])

    def test_metrics_exclude_nonoutcomes_unmatched_cases_and_missing_values(self):
        m, rows = inferential(4)
        rows = [row for row in rows if (row['revision'], row['case']) != ('after', '1')]
        for row in rows:
            row['wall_seconds'] = 999
            if row['revision'] == 'after' and row['case'] == '0':
                row.update(status='interrupted', success=None)
            if row['case'] == '2':
                row['wall_seconds'] = None if row['revision'] == 'after' else 999
            if row['case'] == '3':
                row['wall_seconds'] = 20 if row['revision'] == 'after' else 10
        metric = compare(m, rows)['slices'][0]['metrics']['wall_seconds']
        self.assertEqual(metric['paired_outcomes'], 2)
        self.assertEqual(metric['paired_values'], 1)
        self.assertEqual((metric['baseline_mean'], metric['candidate_mean'], metric['mean_change']),
                         (10, 20, 10))


class StatisticsTests(unittest.TestCase):
    def test_exact_sign_test_enumerated(self):
        for n in range(20):
            for losses in range(n + 1):
                expected = sum(math.comb(n, k) / 2 ** n for k in range(losses, n + 1))
                self.assertEqual(regression_p(losses, n - losses), expected)

    def test_zero_loss_bound_closed_form(self):
        for n in (1, 10, 100, 1000):
            self.assertAlmostEqual(harmful_flip_upper_bound(0, n, .05), 1 - .05 ** (1 / n))

    def test_full_loss_bound(self):
        self.assertEqual(harmful_flip_upper_bound(10, 10, .05), 1)

    def test_bound_solves_independent_small_binomial_sum(self):
        for n in (2, 5, 10, 20):
            for losses in range(1, n):
                bound = harmful_flip_upper_bound(losses, n, .05)
                cdf = sum(math.comb(n, j) * bound ** j * (1 - bound) ** (n - j)
                          for j in range(losses + 1))
                self.assertAlmostEqual(cdf, .05, places=11)

    def test_bounds_monotone_in_losses(self):
        values = [harmful_flip_upper_bound(k, 20, .05) for k in range(21)]
        self.assertEqual(values, sorted(values))

    def test_invalid_bound_inputs(self):
        for args in ((0, 0, .05), (-1, 10, .05), (11, 10, .05), (True, 10, .05), (1, 10, 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                harmful_flip_upper_bound(*args)

    def test_invalid_sign_counts_even_after_cache_warmup(self):
        regression_p(1, 2)
        for args in ((True, 2), (1.0, 2), (-1, 2), (1001, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                regression_p(*args)


if __name__ == '__main__':
    unittest.main()
