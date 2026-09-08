"""Fault injection at the worker transport and atomic checkpoint boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from policydiff.execution_records import atomic_write, collect_receipts, read_receipt, receipt
from policydiff.io import encode
from policydiff.schema import EvidenceError


class ExecutionRecordTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'record.json'
        self.result = {'status': 'completed', 'success': True, 'reason': 'official_success', 'steps': 1,
                       'input_integrity': 'verified',
                       'physical_state_sha256': 'b' * 64, 'rng_sha256': 'c' * 64}
        self.packet = receipt('a' * 64, 0, self.result, 'synthetic-admission')

    def read(self):
        return read_receipt(self.path, 'a' * 64, 0, 20, 'synthetic-admission')

    def test_valid_receipt_roundtrip(self):
        atomic_write(self.path, encode(self.packet))
        self.assertEqual(self.read(), self.result)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_failed_publish_preserves_previous_complete_checkpoint(self):
        atomic_write(self.path, b'old-complete')
        with patch('policydiff.execution_records.os.replace', side_effect=OSError('synthetic replace failure')):
            with self.assertRaises(OSError):
                atomic_write(self.path, b'new-complete')
        self.assertEqual(self.path.read_bytes(), b'old-complete')
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_failed_sync_never_publishes_partial_checkpoint(self):
        atomic_write(self.path, b'old-complete')
        with patch('policydiff.execution_records.os.fsync', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                atomic_write(self.path, b'new-complete')
        self.assertEqual(self.path.read_bytes(), b'old-complete')
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_plan_trial_and_admission_identity_are_all_required(self):
        for key, value in (('plan_sha256', 'd' * 64), ('index', 1), ('index', False),
                           ('trial_id', 'another-run'), ('trial_receipt_schema_version', True),
                           ('trial_receipt_schema_version', 2), ('unknown', 1)):
            with self.subTest(key=key, value=value):
                self.path.write_bytes(encode(dict(self.packet, **{key: value})))
                with self.assertRaises(EvidenceError):
                    self.read()

    def test_malformed_transport_never_becomes_a_policy_failure(self):
        cases = [b'{', b'[]', b'null', b'{}', b'\xff', b'{"x":0,"x":1}', b'{"x":NaN}',
                 b'{"x":1e999}', b'{} {}', b'x' * 32769]
        for data in cases:
            with self.subTest(data=data[:25]):
                self.path.write_bytes(data)
                with self.assertRaises(EvidenceError):
                    self.read()

    def test_worker_result_fields_cannot_override_accounting_or_fake_outcomes(self):
        for key, value in (('status', 'unknown'), ('success', 'true'), ('success', 1), ('success', None),
                           ('steps', 0), ('steps', 21), ('steps', True), ('reason', 'horizon_reached'),
                           ('physical_state_sha256', ''), ('rng_sha256', None), ('arm', 'candidate'),
                           ('wall_seconds', True), ('wall_seconds', -1), ('wall_seconds', 10 ** 400),
                           ('runtime_versions', []), ('cleanup_error', {})):
            packet = deepcopy(self.packet)
            packet['result'][key] = value
            with self.subTest(key=key, value=str(value)[:30]):
                self.path.write_bytes(encode(packet))
                with self.assertRaises(EvidenceError):
                    self.read()

    def test_non_outcomes_allow_no_fabricated_success_or_missing_required_fields(self):
        for status in ('infrastructure_error', 'interrupted'):
            result = {'status': status, 'success': None, 'reason': 'synthetic_fault', 'input_integrity': 'not_checked'}
            self.path.write_bytes(encode(receipt('a' * 64, 0, result, 'synthetic-admission')))
            self.assertEqual(self.read(), result)
            result['success'] = False
            self.path.write_bytes(encode(receipt('a' * 64, 0, result, 'synthetic-admission')))
            with self.assertRaises(EvidenceError):
                self.read()

    def test_horizon_and_invalid_action_reasons_match_executed_steps(self):
        for status, reason, steps, accepted in [('completed', 'horizon_reached', 20, True),
                                               ('completed', 'horizon_reached', 1, False),
                                               ('policy_failure', 'invalid_action', 0, True),
                                               ('policy_failure', 'invalid_action', 20, False)]:
            result = dict(self.result, status=status, success=False, reason=reason, steps=steps)
            self.path.write_bytes(encode(receipt('a' * 64, 0, result, 'synthetic-admission')))
            if accepted:
                self.assertEqual(self.read(), result)
            else:
                with self.assertRaises(EvidenceError):
                    self.read()

    def test_pending_input_seal_retains_endpoint_but_blocks_comparison(self):
        result = dict(self.result, input_integrity='pending')
        atomic_write(self.root / 'terminal.json', encode(receipt('a' * 64, 0, result, 'synthetic-admission')))
        collected = collect_receipts(self.root, 'a' * 64, 0, 20, 'synthetic-admission')
        self.assertTrue(collected['success'])
        self.assertIn('integrity_error', collected)
        self.assertIn('cleanup_error', collected)
