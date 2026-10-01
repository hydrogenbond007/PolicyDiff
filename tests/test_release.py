"""Release tooling tests load its clean-source script, never the source package."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile


script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_release.py'
spec = importlib.util.spec_from_file_location('policydiff_release_check', script)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'source'
        self.root.mkdir()
        for name in release.REQUIRED_TOP:
            self.write(name)
        self.output = self.root / 'current-check'
        self.output.mkdir()

    def write(self, name, data=b'fixture'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def inventory(self):
        return {path.relative_to(self.root).as_posix()
                for path in release.source_inventory(self.root, self.output)}

    def test_complete_supported_inventory_without_git(self):
        extras = {'src/policydiff/__init__.py', 'src/policydiff/submodule/code.py',
                  'tests/test_example.py', 'scripts/check_release.py', '.github/workflows/ci.yml', 'LICENSE',
                  'docs/CLI.md', 'docs/assets/libero-demo.gif'}
        for name in extras:
            self.write(name)
        self.assertEqual(self.inventory(), set(release.REQUIRED_TOP) | extras)

    def test_unsupported_source_files_are_not_silently_dropped(self):
        for name in ('src/policydiff/asset.txt', '.github/workflows/extra.yaml',
                     'extra.txt', 'docs/extra.txt', 'docs/assets/unreviewed.gif', 'src/other_package/code.py'):
            with self.subTest(name=name):
                path = self.write(name)
                with self.assertRaisesRegex(RuntimeError, 'unsupported release source file'):
                    self.inventory()
                path.unlink()

    def test_only_explicit_generated_and_current_output_paths_are_excluded(self):
        for name in release.EXCLUDED_ROOT_DIRS:
            self.write(name + '/ignored.bin')
        for name in release.EXCLUDED_ROOT_FILES:
            self.write(name)
        self.write('src/policydiff/__pycache__/cached.pyc')
        self.write('src/policydiff.egg-info/PKG-INFO')
        self.write('current-check/arbitrary.bin')
        self.assertEqual(self.inventory(), set(release.REQUIRED_TOP))
        self.write('other-check/arbitrary.bin')
        with self.assertRaisesRegex(RuntimeError, 'other-check/arbitrary.bin'):
            self.inventory()

    def test_generated_root_directory_names_do_not_hide_nested_source_assets(self):
        self.write('src/policydiff/build/asset.txt')
        with self.assertRaisesRegex(RuntimeError, 'src/policydiff/build/asset.txt'):
            self.inventory()

    def test_generated_metadata_file_names_do_not_hide_directories(self):
        self.write('PKG-INFO/hidden.txt')
        with self.assertRaisesRegex(RuntimeError, 'PKG-INFO/hidden.txt'):
            self.inventory()

    def test_missing_required_source_is_reported(self):
        (self.root / 'README.md').unlink()
        with self.assertRaisesRegex(RuntimeError, 'required release file missing: README.md'):
            self.inventory()

    def test_symlink_source_files_and_directories_are_rejected(self):
        outside = self.root.parent / 'outside'
        outside.mkdir()
        for name, target in (('LICENSE', self.root / 'README.md'), ('src', outside)):
            with self.subTest(name=name):
                path = self.root / name
                try:
                    path.symlink_to(target, target_is_directory=target.is_dir())
                except OSError as exc:
                    self.skipTest(f'symlinks unavailable: {exc}')
                with self.assertRaisesRegex(RuntimeError, 'symlink source'):
                    self.inventory()
                path.unlink()


class ReleaseCommandTests(unittest.TestCase):
    def test_timeout_preserves_partial_logs_and_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            commands, diagnostics = [], io.StringIO()
            timeout = subprocess.TimeoutExpired(['fixture-command'], 120,
                                                output=b'partial stdout\xff', stderr=b'partial stderr')
            with patch.object(release.subprocess, 'run', side_effect=timeout) as child:
                with contextlib.redirect_stderr(diagnostics), self.assertRaisesRegex(RuntimeError, 'timed out after 120s'):
                    release.run_logged('fixture', ['fixture-command'], cwd=output, output=output,
                                       env={}, commands=commands)
            self.assertEqual(child.call_args.kwargs['timeout'], 120)
            self.assertEqual((output / 'fixture.stdout.txt').read_text(encoding='utf-8'), 'partial stdout\ufffd')
            self.assertEqual((output / 'fixture.stderr.txt').read_text(encoding='utf-8'), 'partial stderr')
            self.assertEqual(commands, [{'label': 'fixture', 'exit_code': None, 'expected': 0,
                                         'timed_out': True, 'timeout_seconds': 120}])
            self.assertIn('partial stderr', diagnostics.getvalue())

    def test_expected_nonzero_exit_is_recorded_without_failure(self):
        with tempfile.TemporaryDirectory() as root:
            output, commands = Path(root), []
            result = subprocess.CompletedProcess(['fixture-command'], 3, 'stdout', 'stderr')
            with patch.object(release.subprocess, 'run', return_value=result):
                returned = release.run_logged('fixture', result.args, cwd=output, output=output,
                                              env={}, commands=commands, expected=3)
            self.assertIs(returned, result)
            self.assertEqual(commands, [{'label': 'fixture', 'exit_code': 3, 'expected': 3}])


class SourceDistributionTests(unittest.TestCase):
    def check(self, members, expected=None):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            for name, content in members:
                member = tarfile.TarInfo(name)
                if content is None:
                    member.type, member.linkname = tarfile.SYMTYPE, 'elsewhere'
                    archive.addfile(member)
                else:
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
        data.seek(0)
        if expected is None:
            expected = {'tests/test_new.py': hashlib.sha256(b'new test').hexdigest()}
        with tarfile.open(fileobj=data) as archive:
            release.verify_sdist_sources(archive, expected)

    def test_entire_inventory_checked_not_just_legacy_sentinel(self):
        self.check([('package/tests/test_new.py', b'new test'), ('package/PKG-INFO', b'metadata')])
        with self.assertRaisesRegex(RuntimeError, 'omitted source: tests/test_new.py'):
            self.check([('package/tests/test_contract.py', b'old test')])

    def test_source_bytes_and_regular_member_required(self):
        for content, message in ((b'changed test', 'changed source'), (None, 'non-regular')):
            with self.subTest(content=content), self.assertRaisesRegex(RuntimeError, message):
                self.check([('package/tests/test_new.py', content)])

    def test_empty_multiple_roots_and_duplicate_members_rejected(self):
        valid = ('package/tests/test_new.py', b'new test')
        for members in ([], [valid, valid], [valid, ('other/README.md', b'doc')]):
            with self.subTest(members=members), self.assertRaisesRegex(RuntimeError, 'one root and unique'):
                self.check(members)


class WheelDistributionTests(unittest.TestCase):
    def check(self, members):
        data = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(data, 'w') as archive:
            warnings.simplefilter('ignore', UserWarning)  # Deliberate duplicate-member fixture.
            for name, content in members:
                archive.writestr(name, content)
        data.seek(0)
        expected = {'src/policydiff/__init__.py': hashlib.sha256(b'module').hexdigest(),
                    'README.md': hashlib.sha256(b'documentation').hexdigest()}
        with zipfile.ZipFile(data) as archive:
            release.verify_wheel_sources(archive, expected)

    def test_package_bytes_match_source_without_requiring_docs_in_wheel(self):
        self.check([('policydiff/', b''), ('policydiff/__init__.py', b'module'),
                    ('policydiff-1.dist-info/METADATA', b'metadata')])

    def test_changed_module_is_rejected_even_if_its_behavior_is_unchanged(self):
        with self.assertRaisesRegex(RuntimeError, 'wheel changed source: policydiff/__init__.py'):
            self.check([('policydiff/__init__.py', b'module\n# build-time mutation')])

    def test_missing_package_module_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'wheel package inventory differs'):
            self.check([('policydiff-1.dist-info/METADATA', b'metadata')])

    def test_extra_package_module_or_asset_is_rejected(self):
        for name in ('policydiff/extra.py', 'policydiff/secret.txt'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'wheel package inventory differs'):
                self.check([('policydiff/__init__.py', b'module'), (name, b'extra')])

    def test_duplicate_archive_members_are_rejected(self):
        for name in ('policydiff/__init__.py', 'policydiff-1.dist-info/METADATA'):
            members = [('policydiff/__init__.py', b'module'),
                       ('policydiff-1.dist-info/METADATA', b'metadata')]
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'wheel must have unique member names'):
                self.check(members + [(name, b'duplicate')])

    def test_installation_data_cannot_override_a_checked_module(self):
        for name in ('policydiff-1.data/purelib/policydiff/__init__.py',
                     'policydiff-1.data/platlib/policydiff/__init__.py',
                     'other_package/__init__.py'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'unexpected top-level'):
                self.check([('policydiff/__init__.py', b'module'), (name, b'override')])

    def test_noncanonical_archive_paths_are_rejected(self):
        for name in ('policydiff/../policydiff/__init__.py', '/policydiff/__init__.py',
                     'policydiff//__init__.py', 'policydiff-1.dist-info/../override.py',
                     'policydiff\\__init__.py', 'policydiff/./__init__.py'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'unsafe wheel member path'):
                self.check([('policydiff/__init__.py', b'module'), (name, b'override')])

    def test_top_level_files_cannot_masquerade_as_package_or_metadata_directories(self):
        for name in ('policydiff', 'policydiff-1.dist-info'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'unexpected top-level'):
                self.check([('policydiff/__init__.py', b'module'), (name, b'extra')])

    def test_exactly_one_metadata_directory_required(self):
        for metadata in ([], [('policydiff-1.dist-info/METADATA', b'metadata'),
                             ('policydiff-2.dist-info/METADATA', b'metadata')]):
            with self.subTest(metadata=metadata), self.assertRaisesRegex(RuntimeError, 'one dist-info directory'):
                self.check([('policydiff/__init__.py', b'module')] + metadata)

    def test_special_or_mislabeled_member_types_are_rejected(self):
        for kind in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFDIR):
            info = zipfile.ZipInfo('policydiff-1.dist-info/METADATA')
            info.create_system = 3
            info.external_attr = (kind | 0o777) << 16
            with self.subTest(kind=kind), self.assertRaisesRegex(RuntimeError, 'non-regular wheel member'):
                self.check([('policydiff/__init__.py', b'module'), (info, b'metadata')])


if __name__ == '__main__':
    unittest.main()
