"""Static, escaped Markdown reporting; no active content or external requests."""
import html
import re
from .schema import sha

MAX_VISIBLE_CASES = 50
MAX_VISIBLE_MISSING = 10


def escape(value):
    value = html.escape(str(value), quote=False)
    return re.sub(r'([\\`*_{\}\[\]()#+.!|>~-])', r'\\\1', value)


def triage_markdown(view):
    comparison = view['comparison']
    ranking = view['ranking']
    totals = comparison['observed_totals']
    lines = [f"# {escape(comparison['title'])} — grouped changes", '',
             f"Evidence: **{escape(comparison['evidence_origin'])}** · "
             f"{escape(comparison['baseline'])} → {escape(comparison['candidate'])}", '',
             f"Grouped by {escape(ranking['group_by'])}; ranked by observed {escape(ranking['rank_by'])} count. "
             f"All {ranking['group_count']} groups shown; ties use label order.", '',
             escape(view['scope']), '',
             f"Full comparison: {totals['lost']} lost / {totals['gained']} gained / {totals['unresolved']} unresolved; "
             f"{totals['paired_outcomes']}/{totals['declared_pairs']} paired/planned slice-cases. "
             f"Required coverage complete: {comparison['required_coverage_complete']} "
             f"({sum(slice_report['required'] for slice_report in view['slices'])} required slices).", '',
             '| Group | Lost | Gained | Unresolved | Paired / planned | Retest losses / gains | Complete / incomplete / untested slices |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for group in view['groups']:
        transitions = group['transitions']
        coverage = group['coverage_counts']
        retest = group['unchanged_retest']
        churn = ('not supplied' if retest is None else
                 f"not measured (0/{retest['declared_pairs']} pairs)" if not retest['pairs'] else
                 f"{retest['churn_losses']} / {retest['churn_gains']} ({retest['pairs']}/{retest['declared_pairs']} pairs)")
        lines.append(f"| {escape(group['label'])} | {transitions['lost']} | {transitions['gained']} | "
                     f"{transitions['unresolved']} | {group['paired_outcomes']} / {group['declared_pairs']} | "
                     f"{churn} | {coverage['complete']} / {coverage['incomplete']} / {coverage['not_tested']} |")
    lines += ['', '## Unresolved evidence', '',
              '| Group | Baseline outcome only | Candidate outcome only | Neither outcome | Eligible / declared slices | Required coverage |',
              '| --- | --- | --- | --- | --- | --- |']
    for group in view['groups']:
        coverage = group['outcome_coverage']
        required = ('not required (0 slices)' if not group['required_slice_count'] else
                    f"{'complete' if group['required_coverage_complete'] else 'incomplete'} "
                    f"({group['required_slice_count']} slices)")
        lines.append(f"| {escape(group['label'])} | {coverage['baseline_only_outcome']} | "
                     f"{coverage['candidate_only_outcome']} | {coverage['neither_outcome']} | "
                     f"{group['eligible_slice_count']} / {len(group['slice_ids'])} | {required} |")
    lines += ['', '## Original slices', '',
              '| Slice | Group | Required | Coverage | Retention assessment |', '| --- | --- | --- | --- | --- |']
    labels = {slice_id: group['label'] for group in view['groups'] for slice_id in group['slice_ids']}
    for slice_report in view['slices']:
        inference = slice_report['inference']
        assessment = inference['status'] if inference['eligible'] else '; '.join(inference['ineligible_reasons'])
        lines.append(f"| {escape(slice_report['id'])} | {escape(labels[slice_report['id']])} | "
                     f"{'yes' if slice_report['required'] else 'no'} | "
                     f"{escape(slice_report['coverage'])} | {escape(assessment)} |")
    lines += ['', 'The JSON view retains per-arm status counts, source hashes and the original inference details.', '']
    lines += ['- ' + escape(limitation) for limitation in comparison['limitations']]
    return '\n'.join(lines) + '\n'


def markdown(report):
    totals = report['observed_totals']
    lines = [f"# {escape(report['title'])}", '',
             f"Evidence: **{escape(report['evidence_origin'])}** · Change: {escape(report['change_kind'])}", '',
             'This report is not a deployment or safety certificate.', '',
             f"Observed changes: **{totals['lost']} lost / {totals['gained']} gained / {totals['unresolved']} unresolved** "
             f"across {totals['declared_pairs']} declared slice-cases; {totals['paired_outcomes']} paired outcomes. "
             f"{report['eligible_slice_count']} slices eligible for retention inference. These totals are not independent pooled trials.", '',
             f"Comparing **{escape(report['baseline'])} → {escape(report['candidate'])}**. "
             f"Unchanged retest: {escape(report['retest'] or 'not supplied')}.", '',
             '## Changes by condition', '',
             '| Slice | Coverage | Paired success, before → after | Lost / gained | Retest churn lost / gained | Inference |',
             '| --- | --- | --- | --- | --- | --- |']
    for sl in report['slices']:
        pairs = sl['observed_pairs']
        n = pairs['pairs']
        score = f"{pairs['baseline_successes']}/{n} → {pairs['candidate_successes']}/{n}; {pairs['declared_pairs']} planned" if n else f"No paired outcomes; {pairs['declared_pairs']} planned"
        retest = sl['unchanged_retest']
        churn = (f"{retest['churn_losses']} / {retest['churn_gains']} ({retest['pairs']}/{retest['declared_pairs']} pairs)"
                 if retest and retest['pairs'] else f"not measured (0/{retest['declared_pairs']} pairs)" if retest else 'not supplied')
        lines.append(f"| {escape(sl['id'])} | {escape(sl['coverage'])} | {score} | "
                     f"{pairs['harmful_flips']} / {pairs['helpful_flips']} | {churn} | {escape(sl['inference']['status'])} |")
    lines += ['', 'Counts above describe observed pairs. Missing and non-outcome records remain below.', '']
    for sl in report['slices']:
        lines += [f"## {escape(sl['id'])}", '',
                  f"Task: {escape(sl['task'])} · Role: {escape(sl['role'])} · Condition: {escape(sl['condition'])}", '',
                  f"Exposure: {escape(sl['exposure_status'])}; upstream: {escape(report['upstream_exposure'])}.", '']
        for rid, counts in sl['revisions'].items():
            statuses = ', '.join(f'{name} {count}' for name, count in sorted(counts['terminal_status_counts'].items()) if count) or 'none'
            missing = counts['missing_cases']
            sample = ', '.join(missing[:MAX_VISIBLE_MISSING])
            missing_text = f"{len(missing)}" + (f" (sample: {sample})" if missing else '')
            lines.append(f"- {escape(rid)}: {counts['successes']} successes / {counts['scored_outcomes']} scored outcomes; "
                         f"{counts['expected']} expected; statuses {escape(statuses)}; "
                         f"missing {escape(missing_text)}.")
        coverage = sl['outcome_coverage']
        lines += ['', f"Outcome coverage: {coverage['both_outcomes']} both; "
                  f"{coverage['baseline_only_outcome']} before only; "
                  f"{coverage['candidate_only_outcome']} after only; "
                  f"{coverage['neither_outcome']} neither."]
        retest = sl['unchanged_retest']
        if retest and not retest['pairs']:
            lines += ['', f"Unchanged retest: no paired outcomes measured / {retest['declared_pairs']} planned. Churn is unknown."]
        elif retest:
            lines += ['', f"Unchanged retest: {retest['churn_losses']} losses / {retest['churn_gains']} gains "
                      f"over {retest['pairs']} paired outcomes / {retest['declared_pairs']} planned. This is not a causal correction."]
            if retest['discordant_pairs']:
                lines += ['', 'Retest warning: unchanged checkpoint produced different outcomes despite matching declared starts/RNG. '
                          'Investigate nondeterminism or incomplete provenance; the observed churn is preserved.']
        if sl['inference']['eligible']:
            inf = sl['inference']
            lines += ['', f"Conditional on declared sampling assumptions: one-sided p={inf['regression_p']:.6g}; "
                      f"harmful-flip upper bound={inf['harmful_flip_probability_upper_bound']:.4f}; "
                      f"per-slice alpha={inf['per_slice_alpha']:.6g}."]
            lines += ['', f"Retest context: {inf['unchanged_retest_discordant_pairs']} discordant pairs. " + escape(inf['churn_caveat'])]
        else:
            lines += ['', 'Formal inference withheld: ' + escape('; '.join(sl['inference']['ineligible_reasons'])) + '.']
        for name, metric in sl['metrics'].items():
            if metric['paired_values']:
                lines += ['', f"{escape(name)}: paired mean {metric['baseline_mean']:.3g} → {metric['candidate_mean']:.3g}; "
                          f"{metric['paired_values']} measured pairs / {metric['paired_outcomes']} outcome pairs. "
                          'Descriptive only; missing measurements and failure/stop censoring may bias this.']
        interesting = [case for case in sl['cases'] if case['transition'] in ('lost', 'gained', 'unresolved')]
        if sl['coverage'] == 'not_tested':
            lines += ['', 'No declared cases were tested. All case IDs remain in report.json.']
        elif interesting:
            lines += ['', '| Case | Change | Candidate record | Evidence reference (unverified) |',
                      '| --- | --- | --- | --- |']
            for case in interesting[:MAX_VISIBLE_CASES]:
                record = case['records'][report['candidate']]
                lines.append(f"| {escape(case['id'])} | {escape(case['transition'])} | "
                             f"{escape(record['status'] if record else 'missing')} | "
                             f"{escape(record['evidence_ref'] or 'not supplied') if record else 'not supplied'} |")
            if len(interesting) > MAX_VISIBLE_CASES:
                lines += ['', f"{len(interesting) - MAX_VISIBLE_CASES} more changed/unresolved cases in report.json."]
        lines.append('')
    lines += ['## Limits', ''] + [f'- {escape(limit)}' for limit in report['limitations']]
    if report.get('inputs'):
        lines += ['', '## Input snapshots', '']
        lines += [f"- {escape(key)}: `{sha(value, 'report input digest')}`" for key, value in report['inputs'].items()]
    return '\n'.join(lines) + '\n'
