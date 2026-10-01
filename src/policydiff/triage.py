"""Display selections from a full comparison; never infer from an outcome filter."""
from copy import deepcopy

from .schema import MAX_TOTAL_CASES, identifier, integer, require

TRANSITIONS = ('lost', 'gained', 'unresolved', 'retained_success', 'shared_failure')
GROUP_FIELDS = ('task', 'axis', 'condition', 'role')
RANK_FIELDS = ('lost', 'unresolved')


def group_changes(report, *, group_by='task', rank_by='lost'):
    """Describe exact metadata groups from a fresh compare() result, not saved JSON."""
    require(group_by in GROUP_FIELDS, 'unsupported grouping field')
    require(rank_by in RANK_FIELDS, 'unsupported ranking field')
    groups = {}
    for slice_report in report['slices']:
        dimensions = ({'axis': slice_report['axis'], 'condition': slice_report['condition']}
                      if group_by == 'condition' else {group_by: slice_report[group_by]})
        key = tuple(dimensions.values())
        label = ' / '.join(key)
        if key not in groups:
            groups[key] = {
                'dimensions': dimensions,
                'label': label, 'slice_ids': [], 'declared_pairs': 0, 'paired_outcomes': 0,
                'transitions': dict.fromkeys(TRANSITIONS, 0),
                'coverage_counts': dict.fromkeys(('complete', 'incomplete', 'not_tested'), 0),
                'required_coverage_complete': True, 'required_slice_count': 0,
                'eligible_slice_count': 0, 'ineligible_reason_counts': {},
                'outcome_coverage': dict.fromkeys(slice_report['outcome_coverage'], 0),
                'revisions': {revision: {'expected': 0, 'records': 0, 'scored_outcomes': 0,
                    'successes': 0, 'missing_records': 0,
                    'terminal_status_counts': dict.fromkeys(counts['terminal_status_counts'], 0)}
                    for revision, counts in slice_report['revisions'].items()},
                'unchanged_retest': None if report['retest'] is None else
                    dict.fromkeys(('pairs', 'declared_pairs', 'churn_losses', 'churn_gains'), 0)}
        group = groups[key]
        group['slice_ids'].append(slice_report['id'])
        group['declared_pairs'] += slice_report['observed_pairs']['declared_pairs']
        group['paired_outcomes'] += slice_report['observed_pairs']['pairs']
        group['coverage_counts'][slice_report['coverage']] += 1
        group['required_slice_count'] += int(slice_report['required'])
        group['eligible_slice_count'] += int(slice_report['inference']['eligible'])
        for reason in slice_report['inference']['ineligible_reasons']:
            group['ineligible_reason_counts'][reason] = group['ineligible_reason_counts'].get(reason, 0) + 1
        for coverage, count in slice_report['outcome_coverage'].items():
            group['outcome_coverage'][coverage] += count
        if slice_report['required'] and slice_report['coverage'] != 'complete':
            group['required_coverage_complete'] = False
        for case in slice_report['cases']:
            group['transitions'][case['transition']] += 1
        for revision, counts in slice_report['revisions'].items():
            target = group['revisions'][revision]
            for field in ('expected', 'records', 'scored_outcomes', 'successes'):
                target[field] += counts[field]
            target['missing_records'] += len(counts['missing_cases'])
            for status, count in counts['terminal_status_counts'].items():
                target['terminal_status_counts'][status] += count
        if group['unchanged_retest'] is not None:
            for field in group['unchanged_retest']:
                group['unchanged_retest'][field] += slice_report['unchanged_retest'][field]
    for group in groups.values():
        group['slice_ids'].sort()
    ordered = sorted(groups.values(), key=lambda group: (-group['transitions'][rank_by], tuple(group['dimensions'].values())))
    return deepcopy({
        'triage_schema_version': 1, 'status': 'changes_grouped',
        'scope': 'Descriptive grouping by exact declared labels; condition groups also include their axis. '
                 'Counts are slice-cases, not unique robot trials; '
                 'the same start may appear in multiple slices. Ranking is an observed count, not severity, '
                 'causality or statistical significance. Groups can mix contracts and exposure roles. '
                 'Inference remains per original slice; retest churn is not subtracted. No evidence files are opened.',
        'ranking': {'group_by': group_by, 'rank_by': rank_by, 'direction': 'descending',
                    'tie_break': 'dimensions_ascending', 'group_count': len(ordered)},
        'comparison': {key: value for key, value in report.items() if key not in ('manifest', 'slices')},
        'groups': ordered,
        'slices': [{key: value for key, value in slice_report.items() if key != 'cases'}
                   for slice_report in report['slices']]})


def select_cases(report, *, slice_ids=None, transitions=None, limit=100):
    """Internal projection of a freshly validated compare() result, not a JSON loader."""
    integer(limit, 'case limit', 1, MAX_TOTAL_CASES)
    declared = [sl['id'] for sl in report['slices']]
    slice_ids = declared if slice_ids is None else slice_ids
    transitions = list(TRANSITIONS[:3]) if transitions is None else transitions
    for values, allowed, label in ((slice_ids, declared, 'slice'), (transitions, TRANSITIONS, 'transition')):
        require(isinstance(values, list) and values, f'need at least one {label} filter')
        for value in values:
            identifier(value, label)
            require(value in allowed, f'unknown {label} filter: {value}')
        require(len(set(values)) == len(values), f'duplicate {label} filter')
    cases, slices, matched = [], [], 0
    for sl in report['slices']:
        selected = sl['id'] in slice_ids
        matches = [case for case in sl['cases'] if selected and case['transition'] in transitions]
        shown = matches[:max(0, limit - len(cases))]
        matched += len(matches)
        cases.extend(dict(case, slice=sl['id']) for case in shown)
        slices.append(dict({key: value for key, value in sl.items() if key != 'cases'},
                           selected_for_display=selected, matching_cases=len(matches), shown_cases=len(shown)))
    return deepcopy({
        'case_view_schema_version': 1, 'status': 'cases_selected',
        'scope': 'Display filter only. Counts, coverage, multiplicity and inference retain the full comparison; '
                 'selected outcomes are not a new test population or a release gate. Evidence references are not opened.',
        'comparison': {key: value for key, value in report.items() if key not in ('manifest', 'slices')},
        'selection': {'slice_ids': [sid for sid in declared if sid in slice_ids],
                      'transitions': [t for t in TRANSITIONS if t in transitions],
                      'limit': limit, 'matching_cases': matched, 'shown_cases': len(cases),
                      'omitted_cases': matched - len(cases), 'truncated': matched > len(cases)},
        'slices': slices, 'cases': cases})
