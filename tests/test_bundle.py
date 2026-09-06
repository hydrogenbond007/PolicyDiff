import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from policydiff import EvidenceError, compare
from policydiff.cli import encode, main, write_bundle
from policydiff.demo import fixture
from policydiff.io import csv_bytes, sha256


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'
        self.assertEqual(self.invoke(['demo', '--output', str(self.bundle)])[0], 0)

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def verify(self, bundle=None):
        return self.invoke(['verify', '--bundle', str(bundle or self.bundle)])

    def marker(self):
        return json.loads((self.bundle / 'COMPLETE.json').read_bytes())

    def save_marker(self, marker):
        (self.bundle / 'COMPLETE.json').write_bytes(encode(marker))

    def test_verify_is_read_only_and_portable(self):
        before = {p.name: p.read_bytes() for p in self.bundle.iterdir()}
        code, output, error = self.verify()
        self.assertEqual((code, error), (0, ''))
        self.assertEqual(json.loads(output)['status'], 'bundle_consistent')
        self.assertIn('not authenticity', json.loads(output)['scope'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.bundle.iterdir()})
        moved = self.root / 'moved'
        shutil.copytree(self.bundle, moved)
        self.assertEqual(self.verify(moved)[0], 0)

    def test_each_modified_payload_is_rejected(self):
        for name in self.marker()['sha256']:
            with self.subTest(name=name):
                copied = self.root / name
                shutil.copytree(self.bundle, copied)
                path = copied / name
                path.write_bytes(path.read_bytes() + b' ')
                code, _, error = self.verify(copied)
                self.assertEqual(code, 2)
                self.assertIn('checksum mismatch', error)

    def test_missing_empty_truncated_and_duplicate_receipts_rejected(self):
        path = self.bundle / 'COMPLETE.json'
        for data in (b'', b'{', b'{"sha256":{},"sha256":{}}'):
            with self.subTest(data=data):
                path.write_bytes(data)
                self.assertEqual(self.verify()[0], 2)
        path.unlink()
        self.assertEqual(self.verify()[0], 2)

    def test_receipt_cannot_select_paths_to_open(self):
        original = self.marker()
        for name in ('../outside', '/outside', 'folder/payload', 'report.json\\outside'):
            with self.subTest(name=name):
                marker = dict(original, sha256=dict(original['sha256'], **{name: 'a' * 64}))
                self.save_marker(marker)
                code, _, error = self.verify()
                self.assertEqual(code, 2)
                self.assertIn('payload names', error)

    def test_symlinked_payload_is_rejected(self):
        path = self.bundle / 'report.md'
        original = self.root / 'original.md'
        path.rename(original)
        path.symlink_to(original)
        self.assertEqual(self.verify()[0], 2)

    def test_receipt_summary_must_match_report(self):
        marker = self.marker()
        marker['eligible_slice_count'] = 999
        self.save_marker(marker)
        self.assertEqual(self.verify()[0], 2)

    def test_unknown_receipt_version_rejected_without_rewriting(self):
        marker = self.marker()
        marker['bundle_schema_version'] = 999
        self.save_marker(marker)
        before = (self.bundle / 'COMPLETE.json').read_bytes()
        self.assertEqual(self.verify()[0], 2)
        self.assertEqual((self.bundle / 'COMPLETE.json').read_bytes(), before)

    def test_unversioned_legacy_marker_needs_explicit_regeneration(self):
        marker = self.marker()
        del marker['bundle_schema_version']
        self.save_marker(marker)
        self.assertEqual(self.verify()[0], 2)

    def test_oversized_member_is_rejected(self):
        from policydiff.bundle import _read_member
        with self.assertRaisesRegex(EvidenceError, 'size limit'):
            _read_member(self.bundle, 'report.json', 1)

    def test_short_payload_write_never_publishes_complete(self):
        from policydiff.bundle import _write_new
        path = self.root / 'short'
        with patch.object(Path, 'open') as opened:
            opened.return_value.__enter__.return_value.write.return_value = 1
            with self.assertRaisesRegex(OSError, 'short write'):
                _write_new(path, b'longer')

    def test_failed_atomic_rename_preserves_partial_without_complete(self):
        target = self.root / 'rename-failure'
        with patch.object(Path, 'replace', side_effect=OSError('injected rename failure')):
            code, _, _ = self.invoke(['demo', '--output', str(target)])
        self.assertEqual(code, 2)
        self.assertFalse((target / 'COMPLETE.json').exists())
        self.assertTrue((target / 'COMPLETE.json.tmp').is_file())
        self.assertTrue((target / 'report.json').is_file())

    def test_exponent_overflow_is_invalid_input_not_internal_error(self):
        path = self.bundle / 'COMPLETE.json'
        original = path.read_bytes()
        for value in (b'1e999', b'-1e999', b'NaN', b'Infinity'):
            with self.subTest(value=value):
                path.write_bytes(original.replace(b'"eligible_slice_count": 0',
                                                 b'"eligible_slice_count": ' + value))
                code, _, error = self.verify()
                self.assertEqual(code, 2)
                self.assertIn('nonfinite', error)

    def test_input_hash_links_are_checked(self):
        marker = self.marker()
        marker['input_sha256']['manifest_sha256'] = 'a' * 64
        self.save_marker(marker)
        self.assertEqual(self.verify()[0], 2)

    def test_producer_version_disagreement_is_rejected(self):
        marker = self.marker()
        marker['version'] += '-mismatch'
        self.save_marker(marker)
        code, _, error = self.verify()
        self.assertEqual(code, 2)
        self.assertIn('producer identity', error)

    def test_unknown_receipt_fields_are_rejected(self):
        marker = self.marker()
        marker['extra'] = 'unexpected'
        self.save_marker(marker)
        code, _, error = self.verify()
        self.assertEqual(code, 2)
        self.assertIn('unknown fields', error)

    def test_coordinated_rewrites_are_not_authenticated(self):
        # An unsigned receipt cannot detect an attacker updating its hashes too.
        path = self.bundle / 'report.md'
        path.write_bytes(b'Coordinately replaced prose\n')
        marker = self.marker()
        marker['sha256']['report.md'] = sha256(path.read_bytes())
        self.save_marker(marker)
        code, output, _ = self.verify()
        self.assertEqual(code, 0)
        self.assertIn('coordinated rewrites', json.loads(output)['scope'])

    def test_failed_marker_write_never_publishes_complete(self):
        m, rows = fixture()
        target = self.root / 'failed-marker'
        original = Path.open

        def fail_marker(path, *args, **kwargs):
            if path.name.startswith('COMPLETE.json'):
                handle = original(path, *args, **kwargs)
                handle.close()  # Simulate creation followed by a failed write.
                raise OSError('injected marker write failure')
            return original(path, *args, **kwargs)

        snapshots = {'manifest.input.json': encode(m), 'episodes.input.csv': csv_bytes(rows)}
        report = compare(m, rows)
        report['inputs'] = {'manifest_sha256': sha256(snapshots['manifest.input.json']),
                            'episodes_sha256': sha256(snapshots['episodes.input.csv'])}
        with patch.object(Path, 'open', fail_marker), self.assertRaises(OSError):
            write_bundle(target, report, snapshots)
        self.assertFalse((target / 'COMPLETE.json').exists())
        self.assertTrue((target / 'report.json').is_file())

    def test_writer_rejects_unsafe_snapshot_names_before_creating_directory(self):
        m, rows = fixture()
        target = self.root / 'unsafe'
        with self.assertRaises(EvidenceError):
            write_bundle(target, compare(m, rows), {'../escaped': b'data'})
        self.assertFalse(target.exists())
        self.assertFalse((self.root / 'escaped').exists())

    def test_stdout_error_reports_that_completed_bundle_survived(self):
        class BrokenOutput(io.StringIO):
            def write(self, text):
                raise OSError('injected stdout failure')

        target = self.root / 'stdout-failure'
        errors = io.StringIO()
        with contextlib.redirect_stdout(BrokenOutput()), contextlib.redirect_stderr(errors):
            code = main(['demo', '--output', str(target)])
        self.assertEqual(code, 2)
        error = json.loads(errors.getvalue())
        self.assertEqual(error['status'], 'output_notification_failed')
        self.assertEqual(error['bundle_status'], 'complete')
        self.assertTrue((target / 'COMPLETE.json').is_file())

    def test_closed_pipe_has_documented_exit_not_shutdown_error(self):
        target = self.root / 'closed-pipe'
        with subprocess.Popen([sys.executable, '-B', '-m', 'policydiff', 'demo', '--output', str(target)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            process.stdout.close()
            code = process.wait(timeout=10)
            error = process.stderr.read().decode()
        self.assertEqual(code, 2, error)
        self.assertEqual(json.loads(error)['status'], 'output_notification_failed')
        self.assertTrue((target / 'COMPLETE.json').is_file())

    def test_verified_bundle_with_closed_output_reports_delivery_failure(self):
        with subprocess.Popen([sys.executable, '-B', '-m', 'policydiff', 'verify', '--bundle', str(self.bundle)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            process.stdout.close()
            code = process.wait(timeout=10)
            error = process.stderr.read().decode()
        self.assertEqual(code, 2, error)
        notice = json.loads(error)
        self.assertEqual(notice['status'], 'output_notification_failed')
        self.assertEqual(notice['result_status'], 'bundle_consistent')

    def test_closed_stderr_preserves_documented_error_exit(self):
        commands = [
            [sys.executable, '-B', '-m', 'policydiff', 'verify', '--bundle', str(self.bundle)],
            [sys.executable, '-B', '-c',
             "from unittest.mock import patch; from policydiff.cli import main; "
             "p=patch('policydiff.cli.fixture',side_effect=RuntimeError('injected')); "
             "p.start(); raise SystemExit(main(['demo','--output','unused']))"]]
        for command, expected in zip(commands, (2, 4)):
            with self.subTest(expected=expected):
                with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                    process.stdout.close()
                    process.stderr.close()
                    self.assertEqual(process.wait(timeout=10), expected)


if __name__ == '__main__':
    unittest.main()
