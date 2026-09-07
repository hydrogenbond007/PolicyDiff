"""Describe recorded protocol differences, never certify comparability or causality."""
from . import __version__
from .schema import EvidenceError, fields, identifier, require, sha, text

MAX_SNAPSHOT_BYTES = 64 * 1024
MAX_FIELDS = 64
LIMITATIONS = (
    'Caller-recorded descriptions only; no configuration, robot or evidence asset is inspected.',
    'Field names and values use exact text equality; no semantic equivalence or unit conversion is inferred.',
    'Absent and unrecorded values are undetermined, not unchanged; fields omitted from both snapshots are invisible.',
    'Matching recorded fields do not establish complete protocols, comparability or physical validity.',
    'A declared contract digest is an unverified association, not a computed or verified snapshot digest.',
    'The same declared digest with changed text needs review, not proof of drift or cause; this signal excludes absent/unrecorded entries. Inspect undetermined counts separately.',
    'This view contains no outcome comparison, statistical inference, deployment pass or change to the v1 pairing gate.',
)


def _validate_snapshot(snapshot):
    fields(snapshot, ('contract_snapshot_schema_version', 'label',
                      'declared_for_contract_sha256', 'fields'), label='contract snapshot')
    require(type(snapshot['contract_snapshot_schema_version']) is int
            and snapshot['contract_snapshot_schema_version'] == 1,
            'unsupported contract snapshot schema version')
    text(snapshot['label'], 'snapshot label')
    if snapshot['declared_for_contract_sha256'] is not None:
        sha(snapshot['declared_for_contract_sha256'], 'declared_for_contract_sha256')
    entries = snapshot['fields']
    require(isinstance(entries, dict) and 1 <= len(entries) <= MAX_FIELDS,
            'snapshot fields must be an object with 1–64 entries')
    for name, entry in entries.items():
        identifier(name, 'snapshot field name')
        fields(entry, ('status', 'value'), label=f'field {name}')
        require(entry['status'] in ('recorded', 'unrecorded'), f'field {name}: unknown status')
        if entry['status'] == 'recorded':
            text(entry['value'], f'field {name} value', 200)
        else:
            require(entry['value'] is None, f'field {name}: unrecorded value must be null')


def describe_contract_change(before, after):
    """Compare two explicit flat snapshots. Unknown fields never count as equal."""
    for side, snapshot in (('before', before), ('after', after)):
        try:
            _validate_snapshot(snapshot)
        except EvidenceError as exc:
            raise EvidenceError(f'{side} snapshot: {exc}', details={'snapshot_side': side}) from exc
    counts = dict.fromkeys(('same', 'changed', 'undetermined'), 0)
    changes = []
    for name in sorted(before['fields'].keys() | after['fields'].keys()):
        left = before['fields'].get(name, {'status': 'absent', 'value': None})
        right = after['fields'].get(name, {'status': 'absent', 'value': None})
        if left['status'] == right['status'] == 'recorded':
            status = 'same' if left['value'] == right['value'] else 'changed'
        else:
            status = 'undetermined'
        counts[status] += 1
        changes.append({'name': name, 'status': status,
                        'before': dict(left), 'after': dict(right)})
    digests = [snapshot['declared_for_contract_sha256'] for snapshot in (before, after)]
    relation = 'undetermined' if None in digests else 'same' if digests[0] == digests[1] else 'different'
    return {
        'contract_change_schema_version': 1,
        'status': 'contract_descriptions_compared',
        'producer': {'name': 'policydiff', 'version': __version__},
        'inputs': None,
        'snapshots': {side: {key: snapshot[key] for key in (
            'contract_snapshot_schema_version', 'label', 'declared_for_contract_sha256')}
            for side, snapshot in (('before', before), ('after', after))},
        'declared_digest_relation': relation,
        'same_declared_digest_with_field_changes': relation == 'same' and counts['changed'] > 0,
        'counts': counts,
        'any_declared_field_changed': counts['changed'] > 0,
        'any_field_undetermined': counts['undetermined'] > 0,
        'fields': changes,
        'limitations': list(LIMITATIONS),
    }
