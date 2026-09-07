"""Display selections from a full comparison; never infer from an outcome filter."""
from copy import deepcopy

from .schema import MAX_TOTAL_CASES, identifier, integer, require

TRANSITIONS = ('lost', 'gained', 'unresolved', 'retained_success', 'shared_failure')


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
