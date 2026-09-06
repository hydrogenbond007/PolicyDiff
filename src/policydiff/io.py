"""Snapshot input bytes once; parse and hash the exact same snapshot."""
import csv
import hashlib
import io
import json
from pathlib import Path

from .schema import COLUMNS, MAX_ROWS, EvidenceError, require

MAX_INPUT_BYTES = 16 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_snapshot(path):
    with Path(path).open('rb') as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    require(len(data) <= MAX_INPUT_BYTES, "input exceeds the 16 MiB preview limit")
    return data


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise EvidenceError(f"nonfinite JSON literal: {value}")


def parse_manifest(data):
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_unique_keys, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"invalid manifest JSON: {exc}") from exc


def parse_csv(data):
    try:
        reader = csv.DictReader(io.StringIO(data.decode('utf-8'), newline=''), strict=True)
        require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames))
                and set(reader.fieldnames) == set(COLUMNS), "CSV header must contain each schema column exactly once")
        rows = []
        for row in reader:
            require(len(rows) < MAX_ROWS, 'CSV exceeds the 30000 row preview limit')
            require(None not in row and all(v is not None for v in row.values()), 'malformed CSV row width')
            rows.append(row)
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise EvidenceError(f"invalid episode CSV: {exc}") from exc


def load_inputs(manifest_path, episodes_path):
    manifest_bytes, episodes_bytes = read_snapshot(manifest_path), read_snapshot(episodes_path)
    return (parse_manifest(manifest_bytes), parse_csv(episodes_bytes),
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
