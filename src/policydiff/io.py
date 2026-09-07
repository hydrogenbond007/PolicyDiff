"""Snapshot input bytes once; parse and hash the exact same snapshot."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path

from .schema import COLUMNS, MAX_ROWS, EvidenceError, fields, require

MAX_INPUT_BYTES = 16 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def read_snapshot(path):
    path = Path(path)
    require(path.is_file(), 'input must be a regular file')
    with path.open('rb') as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    require(len(data) <= MAX_INPUT_BYTES, "input exceeds the 16 MiB preview limit")
    return data


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {ascii(key)[:80]}")
        result[key] = value
    return result


def _nonfinite(value):
    raise EvidenceError(f"nonfinite JSON literal: {value}")


def _finite_float(value):
    number = float(value)
    require(math.isfinite(number), 'nonfinite JSON number')
    return number


def parse_json(data, label='manifest'):
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_unique_keys,
                          parse_constant=_nonfinite, parse_float=_finite_float)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"invalid {label} JSON: {exc}") from exc


def parse_manifest(data):
    return parse_json(data)


def parse_csv(data, *, record_lines=None):
    """Optionally collect ending physical CSV lines, separate from strict row fields."""
    reader, rows = None, []
    header_ok = False
    try:
        reader = csv.DictReader(io.StringIO(data.decode('utf-8'), newline=''), strict=True)
        require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames)),
                "CSV header must contain each schema column exactly once")
        fields(dict.fromkeys(reader.fieldnames), COLUMNS, label='CSV header')
        header_ok = True
        for row in reader:
            require(len(rows) < MAX_ROWS, 'CSV exceeds the 30000 row preview limit')
            require(None not in row and all(v is not None for v in row.values()), 'malformed CSV row width')
            rows.append(row)
            if record_lines is not None:
                record_lines.append(reader.reader.line_num)
        return rows
    except (EvidenceError, UnicodeError, csv.Error) as exc:
        location = {'csv_line_end': reader.reader.line_num} if reader else {}
        if header_ok:
            location['record'] = len(rows) + 1
        message = str(exc) if isinstance(exc, EvidenceError) else f"invalid episode CSV: {exc}"
        raise EvidenceError(message, details=location) from exc


def load_inputs(manifest_path, episodes_path, *, record_lines=None):
    manifest_bytes, episodes_bytes = read_snapshot(manifest_path), read_snapshot(episodes_path)
    return (parse_manifest(manifest_bytes), parse_csv(episodes_bytes, record_lines=record_lines),
            {"manifest_sha256": sha256(manifest_bytes), "episodes_sha256": sha256(episodes_bytes)},
            {"manifest.input.json": manifest_bytes, "episodes.input.csv": episodes_bytes})


def csv_bytes(rows):
    handle = io.StringIO(newline='')
    writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        values = dict(row)
        if type(values.get('success')) is bool:
            values['success'] = '1' if values['success'] else '0'
        writer.writerow(values)
    return handle.getvalue().encode('utf-8')
