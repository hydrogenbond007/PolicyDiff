"""Release tooling tests load its clean-source script, never the source package."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


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
                  'tests/test_example.py', 'scripts/check_release.py', '.github/workflows/ci.yml', 'LICENSE'}
        for name in extras:
            self.write(name)
        self.assertEqual(self.inventory(), set(release.REQUIRED_TOP) | extras)

    def test_unsupported_source_files_are_not_silently_dropped(self):
        for name in ('src/policydiff/asset.txt', '.github/workflows/extra.yaml',
                     'extra.txt', 'docs/extra.md', 'src/other_package/code.py'):
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


if __name__ == '__main__':
    unittest.main()
