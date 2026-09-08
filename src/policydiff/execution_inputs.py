"""Scoped local execution inputs; not exhaustive dependency attestation."""
import hashlib
import importlib.util
import os
from pathlib import Path
import sys

from .io import read_snapshot, sha256
from .schema import require


def file_hash(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'execution inputs must be regular non-symlink files')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _inventory(directory, root, *, python_only=False):
    require(directory.is_dir() and not directory.is_symlink(),
            'LIBERO input directories must exist and not be symlinks')

    def fail(error):
        raise error

    result = {}
    for current, directories, names in os.walk(directory, followlinks=False, onerror=fail):
        for name in directories:
            require(not (Path(current) / name).is_symlink(), 'LIBERO input directories must not be symlinks')
        for name in names:
            path = Path(current) / name
            if not python_only or path.suffix == '.py':
                result[path.relative_to(root).as_posix()] = file_hash(path)
    require(bool(result), 'LIBERO source or assets inventory is empty')
    return dict(sorted(result.items()))


def libero_hashes(root):
    """Inventory source and assets, including additions and outer initializers."""
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'LIBERO root must exist and not be a symlink')
    package = root / 'libero'
    return {'source_sha256': _inventory(package, root, python_only=True),
            'asset_sha256': _inventory(package / 'libero/assets', root)}


def load_adapter(path, expected_sha256):
    """Execute the checked source snapshot; never reuse adapter bytecode caches."""
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'adapter must be a regular non-symlink file')
    snapshot = read_snapshot(path)
    require(sha256(snapshot) == expected_sha256, 'adapter source changed after planning')
    spec = importlib.util.spec_from_file_location('policydiff_user_adapter', path)
    require(spec is not None, 'adapter must be an importable Python source file')
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        exec(compile(snapshot, str(path), 'exec'), module.__dict__)
    except BaseException:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
        raise
    return module
