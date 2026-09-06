"""Exclusive evidence bundles and offline consistency checks, not authentication."""
from pathlib import Path

from ._version import __version__
from .io import MAX_INPUT_BYTES, encode, parse_json, sha256
from .report import markdown
from .schema import fields, require, sha, text

INPUT_FILES = {'manifest_sha256': 'manifest.input.json', 'episodes_sha256': 'episodes.input.csv'}
PAYLOAD_FILES = (*INPUT_FILES.values(), 'report.json', 'report.md')
SUMMARY_KEYS = ('evidence_origin', 'required_coverage_complete', 'eligible_slice_count',
                'observed_totals', 'declared_family_size')
MAX_BUNDLE_FILE_BYTES = 64 * 1024 * 1024
SCOPE = ('Checks payload bytes and linked metadata, not authenticity, scientific validity or policy success; '
         'coordinated rewrites of files and receipt can pass. No analysis is rerun or evidence references opened.')


def _write_new(path, data):
    with path.open('xb') as handle:
        if handle.write(data) != len(data):
            raise OSError(f'short write: {path.name}')


def write_bundle(output, report, snapshots):
    """Write to a new directory; publish the completed receipt by atomic rename."""
    require(isinstance(snapshots, dict) and set(snapshots) == set(INPUT_FILES.values()),
            'snapshots must contain exactly the two supported input payload names')
    require(all(isinstance(data, bytes) for data in snapshots.values()), 'snapshots must be bytes')
    require(all(len(data) <= MAX_INPUT_BYTES for data in snapshots.values()), 'input snapshot exceeds size limit')
    inputs = {key: sha256(snapshots[name]) for key, name in INPUT_FILES.items()}
    require(report.get('inputs') == inputs, 'report input hashes disagree with snapshots')
    payloads = dict(snapshots, **{'report.json': encode(report), 'report.md': markdown(report).encode('utf-8')})
    require(all(len(data) <= MAX_BUNDLE_FILE_BYTES for data in payloads.values()), 'bundle payload exceeds size limit')
    receipt = {'bundle_schema_version': 1, 'status': 'complete', 'producer': 'policydiff',
               'version': __version__, **{key: report[key] for key in SUMMARY_KEYS},
               'input_sha256': inputs, 'sha256': {name: sha256(data) for name, data in payloads.items()}}
    marker = encode(receipt)  # Fail before creating any directory if rendering is broken.
    require(len(marker) <= 64 * 1024, 'bundle receipt exceeds size limit')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        _write_new(output / name, data)
    temporary = output / 'COMPLETE.json.tmp'
    _write_new(temporary, marker)
    temporary.replace(output / 'COMPLETE.json')


def _read_member(directory, name, limit=MAX_BUNDLE_FILE_BYTES):
    path = directory / name
    require(not path.is_symlink() and path.is_file(), f'bundle member must be a regular non-symlink file: {name}')
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    require(len(data) <= limit, f'bundle member exceeds size limit: {name}')
    return data


def verify_bundle(directory):
    """Check the supported bundle layout; never execute or rerun its evidence."""
    directory = Path(directory)
    require(directory.is_dir(), 'bundle must be a directory')
    receipt = parse_json(_read_member(directory, 'COMPLETE.json', 64 * 1024), 'bundle receipt')
    fields(receipt, ('bundle_schema_version', 'status', 'producer', 'version', *SUMMARY_KEYS,
                     'input_sha256', 'sha256'), label='bundle receipt')
    require(type(receipt['bundle_schema_version']) is int and receipt['bundle_schema_version'] == 1,
            'unsupported bundle schema; regenerate older previews from saved inputs')
    require(receipt['status'] == 'complete' and receipt['producer'] == 'policydiff', 'invalid bundle completion identity')
    text(receipt['version'], 'bundle producer version', 80)
    fields(receipt['sha256'], PAYLOAD_FILES, label='bundle payload names')
    fields(receipt['input_sha256'], INPUT_FILES, label='bundle input hashes')
    payloads = {}
    for name in PAYLOAD_FILES:  # Fixed names, never paths selected by a receipt.
        expected = sha(receipt['sha256'][name], f'{name} checksum')
        payloads[name] = _read_member(directory, name)
        require(sha256(payloads[name]) == expected, f'checksum mismatch: {name}')
    inputs = {key: receipt['sha256'][name] for key, name in INPUT_FILES.items()}
    require(receipt['input_sha256'] == inputs, 'receipt input hashes disagree with payload checksums')
    report = parse_json(payloads['report.json'], 'bundle report')
    require(isinstance(report, dict), 'bundle report must be an object')
    for key in ('report_schema_version', 'input_schema_version'):
        require(type(report.get(key)) is int and report[key] == 1, f'unsupported {key}')
    require(report.get('producer') == {'name': 'policydiff', 'version': receipt['version']},
            'report and receipt producer identity disagree')
    require(report.get('inputs') == inputs, 'report input hashes disagree with snapshots')
    require(encode({key: report.get(key) for key in SUMMARY_KEYS}) ==
            encode({key: receipt[key] for key in SUMMARY_KEYS}), 'report and receipt summary disagree')
    manifest = parse_json(payloads['manifest.input.json'], 'bundle manifest')
    require(isinstance(manifest, dict) and type(manifest.get('schema_version')) is int
            and manifest['schema_version'] == report['input_schema_version'], 'manifest schema identity mismatch')
    require(encode(report.get('manifest')) == encode(manifest), 'report manifest disagrees with input snapshot')
    return {'status': 'bundle_consistent', 'bundle': str(directory.resolve()),
            'producer_version': receipt['version'], 'verified_files': list(PAYLOAD_FILES), 'scope': SCOPE}
