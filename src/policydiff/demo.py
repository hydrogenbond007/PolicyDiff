"""Deterministic synthetic examples. Never count these as robot trials."""
import hashlib
from .schema import COLUMNS, MAX_CASES, integer


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture(n=12):
    """Return a mixed synthetic comparison with untested and interrupted slices."""
    integer(n, 'synthetic fixture cases per slice', 1, MAX_CASES)
    base_hash, candidate_hash = digest('synthetic-base'), digest('synthetic-candidate')
    manifest = {
        'schema_version': 1, 'title': 'PolicyDiff synthetic walkthrough', 'evidence_origin': 'synthetic',
        'baseline': {'id': 'before', 'family': 'synthetic-policy', 'checkpoint_sha256': base_hash},
        'candidate': {'id': 'after', 'family': 'synthetic-policy', 'checkpoint_sha256': candidate_hash, 'parent': 'before'},
        'retest': {'id': 'retest', 'family': 'synthetic-policy', 'checkpoint_sha256': base_hash},
        'change': {'kind': 'weights', 'description': 'Synthetic adaptation example; no robot or model was run.',
                   'upstream_exposure': 'unknown'},
        'sampling': {'design': 'fixed_cases', 'frozen_before_outcomes': False, 'alpha': .05,
                     'maximum_harm_probability': .1, 'minimum_baseline_success_rate': .5},
        'slices': []}
    definitions = [
        ('old-nominal', 'pick-known', 'old_rehearsed', 'nominal', 'included', 'included'),
        ('old-camera', 'pick-known', 'old_unrehearsed', 'camera', 'included', 'excluded'),
        ('new-target', 'pick-new', 'adaptation_target', 'nominal', 'excluded', 'included'),
        ('held-out', 'place-unseen', 'held_out', 'object', 'unknown', 'excluded'),
        ('interrupted', 'old-other', 'old_unrehearsed', 'layout', 'included', 'excluded'),
        ('untested', 'future-task', 'held_out', 'dynamics', 'excluded', 'excluded')]
    rows = []
    for sid, task, role, axis, parent_exposure, update_exposure in definitions:
        sl = {'id': sid, 'task': task, 'role': role, 'condition': 'Standard' if axis == 'nominal' else axis + ' variation',
              'axis': axis, 'case_ids': [str(i) for i in range(n)], 'contract_sha256': digest('contract/' + sid),
              'horizon_steps': max(100, 30 + n), 'required': sid != 'untested',
              'parent_exposure': parent_exposure, 'update_exposure': update_exposure}
        manifest['slices'].append(sl)
        if sid == 'untested':
            continue
        for i in range(n):
            before = i < max(1, n - 2)
            after = before
            if sid == 'old-nominal':
                after = (i != 0 and i < n - 1)
            elif sid == 'old-camera':
                after = i < max(1, n // 2)
            elif sid == 'new-target':
                before, after = i < 2, i < n - 2
            elif sid == 'held-out':
                before = after = i < n // 2
            for revision in ('before', 'after', 'retest'):
                row = dict.fromkeys(COLUMNS, '')
                row.update(revision=revision, slice=sid, case=str(i), status='completed',
                           success=after if revision == 'after' else before,
                           checkpoint_sha256=candidate_hash if revision == 'after' else base_hash,
                           contract_sha256=sl['contract_sha256'], physical_state_sha256=digest(f'{sid}/physical/{i}'),
                           rng_sha256=digest(f'{sid}/rng/{i}'), steps=30 + i,
                           wall_seconds=1.5 + i / 10)
                if revision == 'retest' and sid == 'old-nominal' and i == 1:
                    row['success'] = False  # Preserved unexplained nondeterminism, not silently rejected.
                if sid == 'interrupted' and revision == 'after' and i == n - 1:
                    row.update(status='interrupted', success='', steps=10, wall_seconds=.5)
                rows.append(row)
    return manifest, rows
