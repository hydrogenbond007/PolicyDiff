"""Synthetic incident-shaped checks; no recorded robot results or causal claims."""
import contextlib
from copy import deepcopy
import io
import itertools
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from policydiff import EvidenceError, compare, describe_contract_change
from policydiff.cli import main
from policydiff.contract import MAX_SNAPSHOT_BYTES
from policydiff.demo import fixture
from policydiff.io import encode, read_snapshot, sha256


def snapshot():
    return {'contract_snapshot_schema_version': 1, 'label': 'Synthetic protocol',
            'declared_for_contract_sha256': 'a' * 64,
            'fields': {'budget.wall_seconds': {'status': 'recorded', 'value': '600'},
                       'controller.kind': {'status': 'recorded', 'value': 'waypoint'},
                       'success.post_release': {'status': 'unrecorded', 'value': None}}}


class ContractChangeTests(unittest.TestCase):
    def test_changed_budget_under_same_declared_digest_needs_review(self):
        before, after = snapshot(), snapshot()
        after['fields']['budget.wall_seconds']['value'] = '3600'
        result = describe_contract_change(before, after)
        self.assertEqual(result['counts'], {'same': 1, 'changed': 1, 'undetermined': 1})
        self.assertEqual(result['declared_digest_relation'], 'same')
        self.assertTrue(result['same_declared_digest_with_field_changes'])
        self.assertTrue(result['any_declared_field_changed'])
        self.assertTrue(result['any_field_undetermined'])
        self.assertIsNone(result['inputs'])
        self.assertNotIn('comparable', result)
        self.assertNotIn('declaration_conflict', result)  # Changed text need not mean actual drift.
        self.assertTrue(result['limitations'])

    def test_digest_relation_never_computes_or_certifies_a_contract(self):
        for left, right, relation in (('a' * 64, 'b' * 64, 'different'),
                                      (None, None, 'undetermined'),
                                      (None, 'a' * 64, 'undetermined'),
                                      ('a' * 64, None, 'undetermined')):
            before, after = snapshot(), snapshot()
            before['declared_for_contract_sha256'] = left
            after['declared_for_contract_sha256'] = right
            after['fields']['budget.wall_seconds']['value'] = '601'
            with self.subTest(relation=relation):
                result = describe_contract_change(before, after)
                self.assertEqual(result['declared_digest_relation'], relation)
                self.assertFalse(result['same_declared_digest_with_field_changes'])

    def test_all_unrecorded_is_not_all_same(self):
        value = snapshot()
        value['fields'] = {'success_rule': {'status': 'unrecorded', 'value': None}}
        result = describe_contract_change(value, value)
        self.assertEqual(result['counts'], {'same': 0, 'changed': 0, 'undetermined': 1})
        self.assertFalse(result['any_declared_field_changed'])
        self.assertTrue(result['any_field_undetermined'])

    def test_all_recorded_same_still_carries_limitations(self):
        value = snapshot()
        del value['fields']['success.post_release']
        result = describe_contract_change(value, value)
        self.assertEqual(result['counts'], {'same': 2, 'changed': 0, 'undetermined': 0})
        self.assertFalse(result['any_field_undetermined'])
        self.assertIn('fields omitted from both snapshots are invisible', ' '.join(result['limitations']))

    def test_unknowns_under_equal_digest_do_not_set_recorded_change_signal(self):
        before, after = snapshot(), snapshot()
        after['fields']['controller.kind'] = {'status': 'unrecorded', 'value': None}
        del after['fields']['budget.wall_seconds']
        result = describe_contract_change(before, after)
        self.assertEqual(result['declared_digest_relation'], 'same')
        self.assertFalse(result['same_declared_digest_with_field_changes'])
        self.assertTrue(result['any_field_undetermined'])
        self.assertIn('this signal excludes absent/unrecorded entries', ' '.join(result['limitations']))

    def test_absence_and_unrecorded_preserved_separately_in_both_directions(self):
        entries = (None, {'status': 'unrecorded', 'value': None},
                   {'status': 'recorded', 'value': '20'}, {'status': 'recorded', 'value': '30'})
        for left, right in itertools.product(entries, repeat=2):
            before, after = snapshot(), snapshot()
            before['fields'], after['fields'] = {}, {}
            # A shared known field keeps even the both-absent case nonempty.
            for item in (before, after):
                item['fields']['anchor'] = {'status': 'recorded', 'value': 'known'}
            if left is not None:
                before['fields']['setting'] = left
            if right is not None:
                after['fields']['setting'] = right
            result = describe_contract_change(before, after)
            reverse = describe_contract_change(after, before)
            self.assertEqual(result['counts'], reverse['counts'])
            for forward, backward in zip(result['fields'], reverse['fields']):
                self.assertEqual(forward['before'], backward['after'])
                self.assertEqual(forward['after'], backward['before'])
                self.assertEqual(forward['status'], backward['status'])
            if left is None and right is None:
                self.assertEqual(len(result['fields']), 1)
                continue
            field = result['fields'][1]
            self.assertEqual(field['before'], left or {'status': 'absent', 'value': None})
            self.assertEqual(field['after'], right or {'status': 'absent', 'value': None})
            if left is None or right is None or 'unrecorded' in (left['status'], right['status']):
                self.assertEqual(field['status'], 'undetermined')

    def test_literal_values_are_not_normalized_or_interpreted(self):
        for left, right in (('20', '20.0'), ('1 s', '1000 ms'), ('false', 'False'), ('a,b', 'b,a')):
            before, after = snapshot(), snapshot()
            before['fields']['controller.kind']['value'] = left
            after['fields']['controller.kind']['value'] = right
            self.assertEqual(describe_contract_change(before, after)['counts']['changed'], 1)

    def test_no_input_mutation_or_output_aliases_and_stable_order(self):
        before, after = snapshot(), snapshot()
        original = deepcopy(before)
        after['fields'] = dict(reversed(list(after['fields'].items())))
        result = describe_contract_change(before, after)
        self.assertEqual(encode(result), encode(describe_contract_change(after, before)))
        self.assertEqual([f['name'] for f in result['fields']], sorted(before['fields']))
        result['fields'][0]['before']['value'] = 'mutated'
        result['snapshots']['before']['label'] = 'mutated'
        result['limitations'].clear()
        self.assertEqual(before, original)
        self.assertEqual(after, original)
        self.assertTrue(describe_contract_change(before, after)['limitations'])

    def test_versioned_envelope_and_asymmetric_metadata_orientation(self):
        before, after = snapshot(), snapshot()
        before['label'], after['label'] = 'Before', 'After'
        after['declared_for_contract_sha256'] = 'b' * 64
        after['fields']['controller.kind']['value'] = 'raw'
        result = describe_contract_change(before, after)
        self.assertEqual(set(result), {'contract_change_schema_version', 'status', 'producer',
            'inputs', 'snapshots', 'declared_digest_relation', 'same_declared_digest_with_field_changes',
            'counts', 'any_declared_field_changed', 'any_field_undetermined', 'fields', 'limitations'})
        reverse = describe_contract_change(after, before)
        for side, opposite, original in (('before', 'after', before), ('after', 'before', after)):
            self.assertEqual(result['snapshots'][side], {key: original[key] for key in
                ('contract_snapshot_schema_version', 'label', 'declared_for_contract_sha256')})
            self.assertEqual(result['snapshots'][side], reverse['snapshots'][opposite])
        self.assertEqual(set(result['snapshots']), {'before', 'after'})
        self.assertEqual(set(result['producer']), {'name', 'version'})
        for field in result['fields']:
            self.assertEqual(set(field), {'name', 'status', 'before', 'after'})

    def test_unknown_envelope_and_entry_keys_rejected(self):
        for key in ('complete', 'verified', 'source_path', 'coverage'):
            value = snapshot()
            value[key] = True
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                describe_contract_change(value, snapshot())
        value = snapshot()
        value['fields']['controller.kind']['notes'] = 'unsupported'
        with self.assertRaises(EvidenceError):
            describe_contract_change(value, snapshot())

    def test_required_envelope_and_entry_keys(self):
        for key in snapshot():
            value = snapshot()
            del value[key]
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                describe_contract_change(value, snapshot())
        for key in ('status', 'value'):
            value = snapshot()
            del value['fields']['controller.kind'][key]
            with self.assertRaises(EvidenceError):
                describe_contract_change(snapshot(), value)

    def test_bad_versions_labels_digests_and_fields(self):
        for key, bad in (('contract_snapshot_schema_version', True), ('contract_snapshot_schema_version', 1.0),
                         ('contract_snapshot_schema_version', 2), ('label', ''), ('label', '\x1b[31m'),
                         ('label', 'x' * 161), ('declared_for_contract_sha256', ''),
                         ('declared_for_contract_sha256', 'A' * 64), ('declared_for_contract_sha256', False),
                         ('fields', []), ('fields', None), ('fields', {})):
            value = snapshot()
            value[key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(EvidenceError):
                describe_contract_change(value, snapshot())
        for bad in (None, False, [], '', 0):
            with self.assertRaises(EvidenceError):
                describe_contract_change(bad, snapshot())

    def test_entry_objects_status_and_value_types_are_strict(self):
        bad_entries = [None, False, [], '', 0, {'status': 'absent', 'value': None},
                       {'status': 'unrecorded', 'value': ''}, {'status': 'unrecorded', 'value': False},
                       {'status': False, 'value': None}]
        bad_entries += [{'status': 'recorded', 'value': v} for v in
                        (None, False, 20, 20.0, [], {}, '', ' untrimmed', '\n', 'x' * 201)]
        for entry in bad_entries:
            value = snapshot()
            value['fields']['controller.kind'] = entry
            with self.subTest(entry=entry), self.assertRaises(EvidenceError):
                describe_contract_change(value, snapshot())

    def test_field_name_validation_and_count_bounds(self):
        for name in (None, 3, '', 'x' * 81, 'sensor/name', '\x1b[31m', ' camera'):
            value = snapshot()
            value['fields'][name] = {'status': 'recorded', 'value': 'known'}
            with self.subTest(name=name), self.assertRaises(EvidenceError):
                describe_contract_change(value, snapshot())
        value = snapshot()
        value['fields'] = {f'f{i}': {'status': 'recorded', 'value': 'x' * 200} for i in range(64)}
        self.assertEqual(describe_contract_change(value, value)['counts']['same'], 64)
        value['fields']['extra'] = {'status': 'unrecorded', 'value': None}
        for side in ('before', 'after'):
            with self.subTest(side=side), self.assertRaises(EvidenceError) as caught:
                describe_contract_change(**{side: value, 'after' if side == 'before' else 'before': snapshot()})
            self.assertEqual(caught.exception.details['snapshot_side'], side)

    def test_exact_name_label_and_value_limits_are_accepted(self):
        value = snapshot()
        value['label'] = 'x' * 160
        value['fields'] = {'x' * 80: {'status': 'recorded', 'value': 'x' * 200}}
        self.assertEqual(describe_contract_change(value, value)['counts']['same'], 1)

    def test_disjoint_maximum_snapshots_preserve_entire_union(self):
        before, after = snapshot(), snapshot()
        for side, value in (('a', before), ('b', after)):
            value['fields'] = {f'{side}{i}': {'status': 'recorded', 'value': 'known'} for i in range(64)}
        result = describe_contract_change(before, after)
        self.assertEqual(result['counts']['undetermined'], 128)
        self.assertEqual(len(result['fields']), 128)

    def test_comparison_contract_stays_separate(self):
        manifest, rows = fixture()
        report = compare(manifest, rows)
        describe_contract_change(snapshot(), snapshot())
        self.assertEqual(report, compare(manifest, rows))
        manifest['contract_snapshot'] = snapshot()
        with self.assertRaisesRegex(EvidenceError, 'unknown fields'):
            compare(manifest, rows)

    def invoke(self, before=None, after=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'before.json').write_bytes(encode(snapshot()) if before is None else before)
            (root / 'after.json').write_bytes(encode(snapshot()) if after is None else after)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['inspect-contract', '--before', str(root / 'before.json'),
                             '--after', str(root / 'after.json')])
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['after.json', 'before.json'])
            return code, out.getvalue(), err.getvalue()

    def test_cli_changed_is_zero_and_hashes_exact_snapshots_read_once(self):
        after = snapshot()
        after['label'] = 'Distinct after label'
        after['fields']['budget.wall_seconds']['value'] = '3600'
        before_bytes, after_bytes = b' ' + encode(snapshot()), encode(after) + b'\n'
        with patch('policydiff.cli.read_snapshot', wraps=read_snapshot) as read:
            code, out, err = self.invoke(before_bytes, after_bytes)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(read.call_count, 2)
        result = json.loads(out)
        self.assertTrue(result['any_declared_field_changed'])
        self.assertEqual(result['snapshots']['before']['label'], snapshot()['label'])
        self.assertEqual(result['snapshots']['after']['label'], after['label'])
        self.assertEqual(result['inputs'], {'before_snapshot_sha256': sha256(before_bytes),
                                          'after_snapshot_sha256': sha256(after_bytes)})
        self.assertEqual(result['contract_change_schema_version'], 1)

    def test_cli_duplicate_keys_nonfinite_invalid_utf8_and_schema_rejected(self):
        for data in (b'', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'\xff', b'[]', b'{}'):
            for side in ('before', 'after'):
                with self.subTest(data=data, side=side):
                    code, out, err = self.invoke(**{side: data})
                    self.assertEqual((code, out), (2, ''))
                    self.assertEqual(json.loads(err)['status'], 'invalid_input_or_output')
                    self.assertEqual(json.loads(err)['snapshot_side'], side)

    def test_cli_byte_limit_accepts_boundary_and_rejects_extra_byte(self):
        data = encode(snapshot())
        data += b' ' * (MAX_SNAPSHOT_BYTES - len(data))
        self.assertEqual(self.invoke(data)[0], 0)
        for side in ('before', 'after'):
            code, out, err = self.invoke(**{side: data + b' '})
            self.assertEqual((code, out), (2, ''))
            self.assertIn('65536 byte limit', json.loads(err)['error'])
            self.assertEqual(json.loads(err)['snapshot_side'], side)

    def test_read_snapshot_limit_checks_and_bounded_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input'
            path.write_bytes(b'abcde')
            self.assertEqual(read_snapshot(path, maximum=5), b'abcde')
            for limit in (0, -1, True, 1.5, 16 * 1024 * 1024 + 1):
                with self.assertRaises(EvidenceError):
                    read_snapshot(path, maximum=limit)
            with self.assertRaises(EvidenceError):
                read_snapshot(path, maximum=4)
            with self.assertRaises(EvidenceError):
                read_snapshot(directory, maximum=5)

    def test_cli_output_failure_still_identifies_completed_description(self):
        with patch('policydiff.cli.encode', side_effect=OSError('output unavailable')):
            code, out, err = self.invoke()
        self.assertEqual((code, out), (2, ''))
        diagnostic = json.loads(err)
        self.assertEqual(diagnostic['status'], 'output_notification_failed')
        self.assertEqual(diagnostic['result_status'], 'contract_descriptions_compared')

    def test_documented_examples_execute_with_stated_counts(self):
        guide = (Path(__file__).resolve().parents[1] / 'SCHEMA.md').read_text(encoding='utf-8')
        guide = guide.split('## Protocol description snapshots\n', 1)[1].split('\n## ', 1)[0]
        examples = re.findall(r'```json\n(.*?)\n```', guide, flags=re.DOTALL)
        self.assertEqual(len(examples), 2)
        code, out, err = self.invoke(*(example.encode() for example in examples))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['counts'], {'same': 1, 'changed': 1, 'undetermined': 1})

    def test_cli_same_path_and_missing_path_side(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_bytes(encode(snapshot()))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['inspect-contract', '--before', str(path), '--after', str(path)])
            self.assertEqual((code, err.getvalue()), (0, ''))
            result = json.loads(out.getvalue())
            self.assertEqual(result['inputs']['before_snapshot_sha256'], result['inputs']['after_snapshot_sha256'])
            self.assertFalse(result['any_declared_field_changed'])
            for side in ('before', 'after'):
                out, err = io.StringIO(), io.StringIO()
                paths = {'before': path, 'after': path, side: path.with_name('missing')}
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(['inspect-contract', '--before', str(paths['before']), '--after', str(paths['after'])])
                self.assertEqual((code, out.getvalue()), (2, ''))
                self.assertEqual(json.loads(err.getvalue())['snapshot_side'], side)

    def test_cli_usage_errors_do_not_enable_a_gate_or_outcome_input(self):
        for args in ([], ['--before', 'before.json'],
                     ['--before', 'before.json', '--after', 'after.json', '--strict-coverage'],
                     ['--before', 'before.json', '--after', 'after.json', '--output', 'out']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(['inspect-contract', *args])
            self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
