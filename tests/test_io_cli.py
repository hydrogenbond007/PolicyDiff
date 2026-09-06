import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from policydiff import EvidenceError, compare
from policydiff.cli import encode, main, write_bundle
from policydiff.demo import fixture
from policydiff.io import csv_bytes, load_inputs, parse_csv, parse_manifest, read_snapshot, sha256
from policydiff.report import markdown
from policydiff.schema import COLUMNS


class IOTests(unittest.TestCase):
    def test_csv_roundtrip(self):
        m, rows = fixture()
        self.assertEqual(compare(m, rows), compare(m, parse_csv(csv_bytes(rows))))

    def test_duplicate_json_keys_rejected_at_any_depth(self):
        for payload in (b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":2}}'):
            with self.assertRaises(EvidenceError):
                parse_manifest(payload)

    def test_nonfinite_and_bad_unicode_json_rejected(self):
        for payload in (b'{"x":NaN}', b'{"x":Infinity}', b'\xff', b'{incomplete'):
            with self.subTest(payload=payload), self.assertRaises(EvidenceError):
                parse_manifest(payload)

    def test_csv_missing_extra_duplicate_headers_rejected(self):
        for columns in (COLUMNS[:-1], COLUMNS + ('extra',), COLUMNS + (COLUMNS[0],)):
            with self.subTest(columns=columns), self.assertRaises(EvidenceError):
                parse_csv((','.join(columns) + '\n').encode())

    def test_csv_malformed_width_and_quoting_rejected(self):
        header = ','.join(COLUMNS).encode() + b'\n'
        for payload in (b'x\n', b','.join([b'x'] * (len(COLUMNS) + 1)), b'"unterminated'):
            with self.subTest(payload=payload), self.assertRaises(EvidenceError):
                parse_csv(header + payload)

    def test_csv_header_only_is_valid_missing_evidence(self):
        self.assertEqual(parse_csv(csv_bytes([])), [])

    def test_csv_row_limit_during_parse(self):
        _, rows = fixture()
        with patch('policydiff.io.MAX_ROWS', 2), self.assertRaisesRegex(EvidenceError, 'row preview limit'):
            parse_csv(csv_bytes(rows[:3]))

    def test_csv_bom_rejected_and_cr_endings_supported(self):
        m, rows = fixture()
        data = csv_bytes(rows)
        with self.assertRaises(EvidenceError):
            parse_csv(b'\xef\xbb\xbf' + data)
        self.assertEqual(compare(m, parse_csv(data.replace(b'\n', b'\r'))), compare(m, rows))

    def test_csv_embedded_newline_reference_and_excessive_field_rejected(self):
        m, rows = fixture()
        rows[0]['evidence_ref'] = 'line1\nline2'
        with self.assertRaises(EvidenceError):
            compare(m, parse_csv(csv_bytes(rows)))
        rows[0]['evidence_ref'] = 'a' * 200000
        with self.assertRaises(EvidenceError):
            parse_csv(csv_bytes(rows))

    def test_exponent_overflow_rejected_and_no_nonfinite_output(self):
        m, rows = fixture()
        data = encode(m).replace(b'"alpha": 0.05', b'"alpha": 1e400')
        with self.assertRaises(EvidenceError):
            compare(parse_manifest(data), rows)
        data = encode(compare(m, rows))
        self.assertNotIn(b'NaN', data)
        self.assertNotIn(b'Infinity', data)

    def test_unmeasured_maximum_population_markdown_is_bounded(self):
        from test_contract import single
        m, _ = single(1000)
        m['slices'] = [dict(m['slices'][0], id=f'slice{i}') for i in range(10)]
        report = compare(m, [])
        output = markdown(report)
        self.assertLess(len(output), 40000)
        self.assertEqual(sum(len(s['cases']) for s in report['slices']), 10000)
        self.assertIn('All case IDs remain in report.json', output)

    def test_markdown_changed_case_limit_is_explicit(self):
        from test_engine import inferential
        m, rows = inferential(100)
        for row in rows:
            if row['revision'] == 'after':
                row['success'] = False
        report = compare(m, rows)
        self.assertEqual(len(report['slices'][0]['cases']), 100)
        self.assertIn('50 more changed/unresolved cases in report.json', markdown(report))

    def test_snapshot_size_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'input'
            p.write_bytes(b'12345')
            with patch('policydiff.io.MAX_INPUT_BYTES', 4), self.assertRaises(EvidenceError):
                read_snapshot(p)

    def test_snapshot_rejects_nonregular_input_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory)]
            if hasattr(os, 'mkfifo'):
                fifo = Path(directory) / 'pipe'
                os.mkfifo(fifo)
                paths.append(fifo)
            for path in paths:
                with self.subTest(path=path), patch.object(Path, 'open') as opened:
                    with self.assertRaisesRegex(EvidenceError, 'regular file'):
                        read_snapshot(path)
                    opened.assert_not_called()

    def test_source_hashes_match_exact_parsed_bytes(self):
        m, rows = fixture()
        mb = json.dumps(m, indent=3).encode() + b'  \n'
        cb = csv_bytes(rows).replace(b'\n', b'\r\n')
        with patch('policydiff.io.read_snapshot', side_effect=[mb, cb]) as reader:
            parsed, records, hashes, snapshots = load_inputs('manifest', 'episodes')
        self.assertEqual(reader.call_count, 2)  # No hash-then-reread race.
        self.assertEqual(parsed, m)
        self.assertEqual(compare(parsed, records), compare(m, rows))
        self.assertEqual(hashes, {'manifest_sha256': sha256(mb), 'episodes_sha256': sha256(cb)})
        self.assertEqual(snapshots, {'manifest.input.json': mb, 'episodes.input.csv': cb})

    def test_markdown_escapes_untrusted_content(self):
        m, rows = fixture()
        m['title'] = '<script>alert(1)</script> [click](https://evil.test) ![image](x) | header'
        m['slices'][0]['condition'] = '<img src=x onerror=alert(1)> | fake'
        for r in rows:
            r['evidence_ref'] = 'evidence/[link](payload).json'
        output = markdown(compare(m, rows))
        self.assertNotIn('<script>', output)
        self.assertNotIn('<img', output)
        self.assertNotIn('[click](', output)
        self.assertNotIn('![image](', output)
        self.assertNotIn('[link](', output)
        self.assertIn('\\| fake', output)

    def test_markdown_rejects_injected_input_digest(self):
        report = compare(*fixture())
        report['inputs'] = {'manifest_sha256': '` [payload](https://invalid.example) `'}
        with self.assertRaises(EvidenceError):
            markdown(report)

    def test_report_planned_denominator_and_untested_present(self):
        m, rows = fixture()
        output = markdown(compare(m, rows))
        self.assertIn('12 planned', output)
        self.assertIn('No paired outcomes', output)
        self.assertIn('Formal inference withheld', output)
        self.assertIn('synthetic', output)
        self.assertIn('Outcome coverage:', output)
        self.assertIn('Retest churn lost / gained', output)
        self.assertIn('wall\\_seconds:', output)

    def test_plain_apostrophe_and_statuses_remain_readable(self):
        m, rows = fixture()
        m['title'] = "Robot's kitchen"
        output = markdown(compare(m, rows))
        self.assertIn("Robot's kitchen", output)
        self.assertIn('completed 12', output)
        self.assertNotIn('x27;', output)

    def test_inferential_markdown_numerical_branches(self):
        from test_engine import inferential
        for n, lose, expected in ((100, False, 'within_declared_harm_bound'),
                                   (12, False, 'inconclusive'), (12, True, 'regression_detected')):
            m, rows = inferential(n)
            if lose:
                for row in rows:
                    if row['revision'] == 'after':
                        row['success'] = False
            report = compare(m, rows)
            self.assertEqual(report['slices'][0]['inference']['status'], expected)
            output = markdown(report)
            self.assertIn('one-sided p=', output)
            self.assertIn('harmful-flip upper bound=', output)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        m, rows = fixture()
        self.manifest = self.root / 'source.json'
        self.episodes = self.root / 'source.csv'
        self.manifest.write_bytes(encode(m))
        self.episodes.write_bytes(csv_bytes(rows))
        self.inputs = ['--manifest', str(self.manifest), '--episodes', str(self.episodes)]

    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_validate_only_no_output_mutation(self):
        before = set(self.root.iterdir())
        code, output, error = self.invoke(['validate'] + self.inputs)
        self.assertEqual((code, error), (0, ''))
        self.assertTrue(json.loads(output)['input_valid'])
        self.assertEqual(set(self.root.iterdir()), before)

    def test_validate_strict_incomplete_exit(self):
        self.assertEqual(self.invoke(['validate'] + self.inputs + ['--strict-coverage'])[0], 3)

    def test_render_failure_does_not_create_output(self):
        dest = self.root / 'render-error'
        with patch('policydiff.bundle.markdown', side_effect=KeyError('injected renderer defect')):
            code, _, _ = self.invoke(['compare'] + self.inputs + ['--output', str(dest)])
        self.assertEqual(code, 4)
        self.assertFalse(dest.exists())

    def test_strict_incomplete_report_still_written(self):
        dest = self.root / 'report'
        code, _, _ = self.invoke(['compare'] + self.inputs + ['--strict-coverage', '--output', str(dest)])
        self.assertEqual(code, 3)
        self.assertTrue((dest / 'COMPLETE.json').is_file())

    def test_stdout_report(self):
        code, output, _ = self.invoke(['compare'] + self.inputs)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['producer']['name'], 'policydiff')

    def test_hashes_and_snapshots_verified(self):
        dest = self.root / 'report'
        code, _, _ = self.invoke(['compare'] + self.inputs + ['--output', str(dest)])
        self.assertEqual(code, 0)
        receipt = json.loads((dest / 'COMPLETE.json').read_text())
        self.assertEqual(receipt['evidence_origin'], 'synthetic')
        self.assertEqual(receipt['eligible_slice_count'], 0)
        self.assertEqual((dest / 'manifest.input.json').read_bytes(), self.manifest.read_bytes())
        self.assertEqual((dest / 'episodes.input.csv').read_bytes(), self.episodes.read_bytes())
        for name, expected in receipt['sha256'].items():
            self.assertEqual(sha256((dest / name).read_bytes()), expected)

    def test_existing_directory_not_overwritten(self):
        dest = self.root / 'report'
        dest.mkdir()
        sentinel = dest / 'report.json'
        sentinel.write_text('do not overwrite')
        code, _, _ = self.invoke(['compare'] + self.inputs + ['--output', str(dest)])
        self.assertEqual(code, 2)
        self.assertEqual(sentinel.read_text(), 'do not overwrite')

    def test_input_file_cannot_be_output(self):
        before = self.manifest.read_bytes()
        code, _, _ = self.invoke(['compare'] + self.inputs + ['--output', str(self.manifest)])
        self.assertEqual(code, 2)
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_output_symlink_refused(self):
        dest = self.root / 'symlink'
        dest.symlink_to(self.root, target_is_directory=True)
        code, _, _ = self.invoke(['compare'] + self.inputs + ['--output', str(dest)])
        self.assertEqual(code, 2)
        self.assertFalse((self.root / 'COMPLETE.json').exists())

    def test_partial_write_no_complete_marker(self):
        dest = self.root / 'partial'
        m, rows = fixture()
        original = Path.open

        def fail_report(path, *args, **kwargs):
            if path.name == 'report.json':
                raise OSError('simulated write failure')
            return original(path, *args, **kwargs)

        report = compare(m, rows)
        report['inputs'] = {'manifest_sha256': sha256(self.manifest.read_bytes()),
                            'episodes_sha256': sha256(self.episodes.read_bytes())}
        with patch.object(Path, 'open', fail_report), self.assertRaises(OSError):
            write_bundle(dest, report, {'manifest.input.json': self.manifest.read_bytes(),
                                      'episodes.input.csv': self.episodes.read_bytes()})
        self.assertTrue((dest / 'manifest.input.json').exists())
        self.assertFalse((dest / 'COMPLETE.json').exists())

    def test_invalid_input_no_output_created(self):
        self.manifest.write_bytes(b'{"x":1,"x":2}')
        dest = self.root / 'invalid'
        code, _, error = self.invoke(['compare'] + self.inputs + ['--output', str(dest)])
        self.assertEqual(code, 2)
        self.assertIn('duplicate JSON key', error)
        self.assertFalse(dest.exists())

    def test_missing_file_is_structured_error(self):
        code, _, error = self.invoke(['validate', '--manifest', str(self.root / 'absent'), '--episodes', str(self.episodes)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(error)['status'], 'invalid_input_or_output')

    def test_internal_error_is_not_input_or_policy_error(self):
        with patch('policydiff.cli.compare', side_effect=KeyError('injected internal defect')):
            code, _, error = self.invoke(['compare'] + self.inputs)
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(error)['status'], 'internal_error')

    def test_demo_roundtrip_and_deterministic_bundles(self):
        a, b = self.root / 'a', self.root / 'b'
        self.assertEqual(self.invoke(['demo', '--output', str(a)])[0], 0)
        self.assertEqual(self.invoke(['compare', '--manifest', str(a / 'manifest.input.json'),
                                     '--episodes', str(a / 'episodes.input.csv'), '--output', str(b)])[0], 0)
        for path in a.iterdir():
            self.assertEqual(path.read_bytes(), (b / path.name).read_bytes())


if __name__ == '__main__':
    unittest.main()
