"""Input debugging must not repair evidence or create a partial comparison."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from policydiff import EvidenceError, compare
from policydiff.cli import main
from policydiff.io import csv_bytes, encode, parse_csv, parse_manifest
from policydiff.schema import COLUMNS, fields, validate_rows
from test_contract import single


class DiagnosticsTests(unittest.TestCase):
    def test_compare_locates_first_bad_record_without_mutation(self):
        manifest, rows = single()
        rows[4]['steps'] = 99999
        before = deepcopy(rows)
        with self.assertRaisesRegex(EvidenceError, 'episode record 5: steps') as caught:
            compare(manifest, rows)
        self.assertEqual(caught.exception.details, {
            'record': 5, **{key: rows[4][key] for key in ('revision', 'slice', 'case')}})
        self.assertEqual(rows, before)

    def test_bounded_diagnostics_scan_all_records_and_skip_pairing(self):
        manifest, rows = single()
        for row in rows[:5]:
            row['success'] = 'not scored'
        # Pairing is also broken, but is not asserted checked after row errors.
        rows[-1]['rng_sha256'] = 'f' * 64
        with self.assertRaises(EvidenceError) as caught:
            validate_rows(manifest, rows, max_errors=3)
        details = caught.exception.details
        self.assertEqual(details['error_count'], 5)
        self.assertEqual([e['record'] for e in details['errors']], [1, 2, 3])
        self.assertTrue(details['errors_truncated'])
        self.assertFalse(details['input_valid'])
        self.assertEqual(details['pairing_checks'], 'skipped')

    def test_error_limit_one_still_counts_all_bad_records(self):
        manifest, rows = single()
        rows[0]['status'] = rows[-1]['status'] = 'pending'
        with self.assertRaises(EvidenceError) as caught:
            validate_rows(manifest, rows, max_errors=1)
        self.assertEqual(caught.exception.details['error_count'], 2)
        self.assertEqual(len(caught.exception.details['errors']), 1)

    def test_collecting_validation_keeps_all_cross_record_checks(self):
        manifest, original = single()
        for mode in ('duplicate', 'pair', 'alias'):
            rows = deepcopy(original)
            if mode == 'duplicate':
                rows[-1] = deepcopy(rows[0])
            elif mode == 'pair':
                rows[-1]['rng_sha256'] = 'f' * 64
            else:
                for row in rows:
                    row['physical_state_sha256'] = 'f' * 64
            with self.subTest(mode=mode), self.assertRaises(EvidenceError):
                validate_rows(manifest, rows, max_errors=20)

    def test_invalid_identifiers_and_cell_contents_not_echoed(self):
        manifest, rows = single()
        rows[0]['case'] = '\x1b[31m|' + 'x' * 5000
        with self.assertRaises(EvidenceError) as caught:
            validate_rows(manifest, rows, max_errors=20)
        detail = caught.exception.details['errors'][0]
        self.assertNotIn('case', detail)
        self.assertNotIn('\x1b', str(caught.exception))
        self.assertLess(len(encode(detail)), 400)

    def test_extra_field_names_escaped_bounded_and_mixed_key_types(self):
        extra = {'\x1b[31m' + 'x' * 5000: 1, None: 2, 3: 4}
        extra.update({f'extra{i}': None for i in range(20)})
        with self.assertRaises(EvidenceError) as caught:
            fields(extra, ())
        message = str(caught.exception)
        self.assertIn('unknown fields', message)
        self.assertIn('more)', message)
        self.assertNotIn('\x1b', message)
        self.assertLess(len(message), 1000)

    def test_duplicate_json_key_is_not_terminal_control_text(self):
        with self.assertRaises(EvidenceError) as caught:
            parse_manifest(b'{"\\u001b[31m":1,"\\u001b[31m":2}')
        self.assertNotIn('\x1b', str(caught.exception))

    def test_csv_record_lines_track_multiline_and_blank_lines(self):
        _, rows = single()
        rows[0]['evidence_ref'] = 'first\nsecond'
        lines = []
        data = csv_bytes(rows[:2]).replace(b'first\nsecond', b'first\n\nsecond')
        parsed = parse_csv(data, record_lines=lines)
        self.assertEqual(lines, [4, 5])
        self.assertEqual(set(parsed[0]), set(COLUMNS))

    def test_csv_parse_failures_located(self):
        header = ','.join(COLUMNS).encode() + b'\n'
        for body in (b'x\n', b'"unfinished\n', b','.join([b'x'] * 13)):
            with self.subTest(body=body), self.assertRaises(EvidenceError) as caught:
                parse_csv(header + body)
            self.assertEqual(caught.exception.details['record'], 1)
            self.assertGreaterEqual(caught.exception.details['csv_line_end'], 2)

    def test_header_errors_are_not_episode_record_errors(self):
        with self.assertRaises(EvidenceError) as caught:
            parse_csv(b'wrong\n')
        self.assertEqual(caught.exception.details, {'csv_line_end': 1})

    def test_standalone_blank_lines_do_not_shift_record_locations(self):
        _, rows = single()
        data = csv_bytes(rows[:2]).splitlines(keepends=True)
        lines = []
        parse_csv(data[0] + data[1] + b'\n\n' + data[2], record_lines=lines)
        self.assertEqual(lines, [2, 5])
        with self.assertRaises(EvidenceError) as caught:
            parse_csv(data[0] + b'\n\nx\n')
        self.assertEqual(caught.exception.details, {'record': 1, 'csv_line_end': 4})

    def test_malformed_and_multiline_headers_have_no_episode_record(self):
        for data, end in ((b'"unfinished', 1), (b'"wrong\nheader"\n', 2),
                          (b'x' * 200000, 1)):
            with self.subTest(end=end), self.assertRaises(EvidenceError) as caught:
                parse_csv(data)
            self.assertEqual(caught.exception.details, {'csv_line_end': end})

    def invoke(self, manifest, rows, *options, command='validate'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'm.json').write_bytes(encode(manifest))
            (root / 'e.csv').write_bytes(csv_bytes(rows))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main([command, '--manifest', str(root / 'm.json'),
                             '--episodes', str(root / 'e.csv'), *options])
            return code, out.getvalue(), err.getvalue()

    def test_cli_json_includes_record_and_ending_csv_line(self):
        manifest, rows = single()
        rows[0]['evidence_ref'] = 'first\nsecond'
        rows[3]['steps'] = 99999
        code, out, err = self.invoke(manifest, rows, '--max-errors', '1')
        self.assertEqual((code, out), (2, ''))
        diagnostic = json.loads(err)
        self.assertEqual(diagnostic['error_count'], 2)
        self.assertEqual(diagnostic['errors'][0]['record'], 1)
        self.assertEqual(diagnostic['errors'][0]['csv_line_end'], 3)
        code, out, err = self.invoke(manifest, rows, command='compare')
        self.assertEqual((code, out), (2, ''))
        self.assertEqual(json.loads(err)['csv_line_end'], 3)

    def test_cli_manifest_error_stays_fail_fast(self):
        manifest, rows = single()
        manifest['sampling']['design'] = 'adaptive'
        code, out, err = self.invoke(manifest, rows)
        self.assertEqual((code, out), (2, ''))
        self.assertNotIn('errors', json.loads(err))

    def test_valid_aggregation_returns_identical_table(self):
        manifest, rows = single()
        self.assertEqual(validate_rows(manifest, rows, max_errors=20), validate_rows(manifest, rows))

    def test_max_errors_bounds_and_type(self):
        manifest, rows = single()
        for value in (0, 101, True, 1.5, '20'):
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                validate_rows(manifest, rows, max_errors=value)
        for value in ('0', '101', 'NaN', '1.5'):
            with self.subTest(value=value), self.assertRaises(SystemExit) as caught:
                self.invoke(manifest, rows, '--max-errors', value)
            self.assertEqual(caught.exception.code, 2)
