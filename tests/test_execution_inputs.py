"""Input-inventory and actual Python-loader tests; no simulator dependencies."""
import importlib.util
import os
from pathlib import Path
import py_compile
import sys
import tempfile
import unittest
from unittest.mock import patch

from policydiff.execution_inputs import file_hash, libero_hashes, load_adapter
from policydiff.io import MAX_INPUT_BYTES, sha256
from policydiff.schema import EvidenceError


class ExecutionInputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.package = self.root / 'libero'
        self.assets = self.package / 'libero/assets'
        self.assets.mkdir(parents=True)
        (self.package / '__init__.py').write_bytes(b'')
        (self.package / 'libero/core.py').write_bytes(b'VALUE = 1\n')
        (self.assets / 'fixture.xml').write_bytes(b'<fixture/>')

    def test_inventory_includes_outer_initializer_and_exact_source_and_asset_bytes(self):
        result = libero_hashes(self.root)
        self.assertEqual(result, {
            'source_sha256': {'libero/__init__.py': sha256(b''),
                              'libero/libero/core.py': sha256(b'VALUE = 1\n')},
            'asset_sha256': {'libero/libero/assets/fixture.xml': sha256(b'<fixture/>')}})

    def test_added_source_or_asset_changes_inventory(self):
        for relative, content, key in (('libero/added.py', b'VALUE = 2\n', 'source_sha256'),
                                        ('libero/assets/added.xml', b'<added/>', 'asset_sha256')):
            with self.subTest(relative=relative):
                before = libero_hashes(self.root)
                path = self.package / relative
                path.write_bytes(content)
                after = libero_hashes(self.root)
                self.assertNotEqual(before[key], after[key])
                self.assertEqual(after[key][path.relative_to(self.root).as_posix()], sha256(content))

    def test_changed_outer_initializer_source_and_asset_are_detected(self):
        for relative, key in (('__init__.py', 'source_sha256'), ('libero/core.py', 'source_sha256'),
                              ('libero/assets/fixture.xml', 'asset_sha256')):
            with self.subTest(relative=relative):
                before = libero_hashes(self.root)
                path = self.package / relative
                path.write_bytes(b'changed')
                self.assertNotEqual(before[key], libero_hashes(self.root)[key])

    def test_missing_or_empty_directories_are_rejected(self):
        with self.assertRaises(EvidenceError):
            libero_hashes(self.root / 'missing')
        empty = self.root / 'empty'
        empty.mkdir()
        with self.assertRaises(EvidenceError):
            libero_hashes(empty)
        (self.assets / 'fixture.xml').unlink()
        with self.assertRaisesRegex(EvidenceError, 'empty'):
            libero_hashes(self.root)
        self.assets.rmdir()
        with self.assertRaises(EvidenceError):
            libero_hashes(self.root)

    def test_empty_source_inventory_is_rejected(self):
        (self.package / '__init__.py').unlink()
        (self.package / 'libero/core.py').unlink()
        with self.assertRaisesRegex(EvidenceError, 'empty'):
            libero_hashes(self.root)

    def test_deleted_file_changes_inventory(self):
        before = libero_hashes(self.root)
        (self.package / 'libero/core.py').unlink()
        self.assertNotEqual(before['source_sha256'], libero_hashes(self.root)['source_sha256'])

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_symlink_inputs_and_directories_are_rejected(self):
        for relative, target, is_directory in (
                ('libero/link.py', self.package / '__init__.py', False),
                ('libero/assets/link.xml', self.assets / 'fixture.xml', False),
                ('libero/linkdir', self.assets, True)):
            path = self.package / relative
            with self.subTest(relative=relative):
                path.symlink_to(target, target_is_directory=is_directory)
                try:
                    with self.assertRaisesRegex(EvidenceError, 'symlink'):
                        libero_hashes(self.root)
                finally:
                    path.unlink()
        link = self.root / 'linked-root'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(EvidenceError, 'symlink'):
            libero_hashes(link)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFOs unavailable')
    def test_nonregular_source_and_assets_are_rejected_without_opening_them(self):
        for relative in ('libero/pipe.py', 'libero/assets/pipe'):
            path = self.package / relative
            os.mkfifo(path)
            try:
                with self.subTest(relative=relative), self.assertRaisesRegex(EvidenceError, 'regular'):
                    libero_hashes(self.root)
            finally:
                path.unlink()

    def test_file_hash_requires_regular_files_and_matches_bytes(self):
        path = self.assets / 'fixture.xml'
        self.assertEqual(file_hash(path), sha256(path.read_bytes()))
        for invalid in (self.assets, self.root / 'missing'):
            with self.subTest(path=invalid), self.assertRaises(EvidenceError):
                file_hash(invalid)

    def test_adapter_executes_checked_source_despite_stale_valid_bytecode(self):
        path = self.root / 'adapter.py'
        old, new = b'VALUE = "old"\n', b'VALUE = "new"\n'
        path.write_bytes(old)
        original = path.stat()
        py_compile.compile(str(path), doraise=True)
        path.write_bytes(new)
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        with patch.dict(sys.modules), patch.object(sys, 'dont_write_bytecode', True):
            # Establish that the ordinary loader really sees a valid stale cache.
            spec = importlib.util.spec_from_file_location('stale_fixture', path)
            stale = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(stale)
            self.assertEqual(stale.VALUE, 'old')
            loaded = load_adapter(path, sha256(new))
            self.assertEqual(loaded.VALUE, 'new')
            self.assertEqual(loaded.__file__, str(path))
            self.assertIs(sys.modules['policydiff_user_adapter'], loaded)

    def test_changed_adapter_is_rejected_before_execution(self):
        path = self.root / 'adapter.py'
        path.write_bytes(b'raise AssertionError("must not execute")\n')
        with self.assertRaisesRegex(EvidenceError, 'changed after planning'):
            load_adapter(path, sha256(b'other'))

    def test_adapter_snapshot_has_a_size_bound(self):
        path = self.root / 'adapter.py'
        with path.open('wb') as handle:
            handle.truncate(MAX_INPUT_BYTES + 1)
        with self.assertRaisesRegex(EvidenceError, 'preview limit'):
            load_adapter(path, '0' * 64)

    def test_failed_adapter_load_restores_previous_module(self):
        path = self.root / 'adapter.py'
        source = b'raise RuntimeError("fixture")\n'
        path.write_bytes(source)
        previous = object()
        with patch.dict(sys.modules, {'policydiff_user_adapter': previous}):
            with self.assertRaisesRegex(RuntimeError, 'fixture'):
                load_adapter(path, sha256(source))
            self.assertIs(sys.modules['policydiff_user_adapter'], previous)
