"""Strict comparison contracts for exact paired synthetic/simulator outcomes."""
from __future__ import annotations

import math
from pathlib import PurePosixPath
import re

MAX_CASES = 1000
MAX_SLICES = 100
MAX_TOTAL_CASES = 10000
MAX_ROWS = MAX_TOTAL_CASES * 3
STATUSES = ("completed", "policy_failure", "infrastructure_error", "interrupted")
OUTCOMES = ("completed", "policy_failure")
ROLES = ("old_rehearsed", "old_unrehearsed", "adaptation_target", "held_out")
COLUMNS = ("revision", "slice", "case", "status", "success", "checkpoint_sha256",
           "contract_sha256", "physical_state_sha256", "rng_sha256", "steps",
           "wall_seconds", "evidence_ref")


class EvidenceError(ValueError):
    """Input cannot support the declared comparison contract."""

    def __init__(self, message, *, details=None):
        super().__init__(message)
        self.details = details or {}


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def text(value, label, maximum=160):
    require(isinstance(value, str) and 0 < len(value) <= maximum
            and value == value.strip() and all(c.isprintable() for c in value),
            f"{label} must be nonempty printable text (max {maximum})")
    return value


def identifier(value, label):
    text(value, label, 80)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value),
            f"{label} must use letters, numbers, underscore, dash or dot")
    return value


def fields(value, required, optional=(), label="object"):
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(required) <= set(value), f"{label} missing fields: {sorted(set(required) - set(value))}")
    extra = set(value) - set(required) - set(optional)
    if extra:
        names = sorted(ascii(key)[:80] for key in extra)
        raise EvidenceError(f"{label} contains unknown fields: {', '.join(names[:10])}"
                            + (f" (+{len(names) - 10} more)" if len(names) > 10 else ""))


def sha(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            f"{label} must be a lowercase SHA-256 digest")
    return value


def integer(value, label, low, high):
    require(type(value) is int and low <= value <= high, f"{label} must be an integer in [{low}, {high}]")
    return value


def probability(value, label):
    require(type(value) in (int, float) and 0 < value < 1 and math.isfinite(value),
            f"{label} must be finite and between zero and one")


def revisions(manifest):
    return [manifest[key] for key in ("baseline", "candidate", "retest") if key in manifest]


def validate_manifest(manifest):
    fields(manifest, ("schema_version", "title", "evidence_origin", "baseline", "candidate",
                      "change", "sampling", "slices"), ("retest",), "manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
            "unsupported manifest schema version")
    text(manifest["title"], "title")
    require(manifest["evidence_origin"] in ("synthetic", "simulation"),
            "v1 supports synthetic or simulation exact-pair evidence; hardware is unsupported")
    for role in ("baseline", "candidate", "retest"):
        if role not in manifest:
            continue
        revision = manifest[role]
        fields(revision, ("id", "checkpoint_sha256", "family"), ("parent",) if role == "candidate" else (), role)
        identifier(revision["id"], f"{role}.id")
        sha(revision["checkpoint_sha256"], f"{role}.checkpoint_sha256")
        text(revision["family"], f"{role}.family")
    base, candidate = manifest["baseline"], manifest["candidate"]
    ids = [r["id"] for r in revisions(manifest)]
    require(len(set(ids)) == len(ids), "revision identifiers must be distinct")
    require(candidate.get("parent") == base["id"], "candidate must name its actual declared parent baseline")
    require(candidate["family"] == base["family"], "v1 compares within a declared model family, not different families")
    if "retest" in manifest:
        retest = manifest["retest"]
        require(retest["checkpoint_sha256"] == base["checkpoint_sha256"] and retest["family"] == base["family"],
                "unchanged retest must match the baseline checkpoint and family")
    fields(manifest["change"], ("kind", "description", "upstream_exposure"), label="change")
    require(manifest["change"]["kind"] in ("weights", "context", "system"), "unknown change kind")
    text(manifest["change"]["description"], "change.description", 500)
    require(manifest["change"]["upstream_exposure"] in ("documented", "unknown"), "upstream exposure must be documented or unknown")
    if manifest["change"]["kind"] == "weights":
        require(candidate["checkpoint_sha256"] != base["checkpoint_sha256"], "weight update must identify different checkpoint bytes")
    else:
        require(candidate["checkpoint_sha256"] == base["checkpoint_sha256"],
                "context/system-only changes must retain checkpoint identity; mixed changes need another protocol")
    sampling = manifest["sampling"]
    fields(sampling, ("design", "frozen_before_outcomes", "alpha", "maximum_harm_probability",
                      "minimum_baseline_success_rate"), label="sampling")
    require(sampling["design"] in ("fixed_cases", "iid_pairs"), "unsupported sampling design; clustered/adaptive tests need another protocol")
    require(type(sampling["frozen_before_outcomes"]) is bool, "frozen_before_outcomes must be Boolean")
    probability(sampling["alpha"], "alpha")
    probability(sampling["maximum_harm_probability"], "maximum_harm_probability")
    probability(sampling["minimum_baseline_success_rate"], "minimum_baseline_success_rate")
    slices = manifest["slices"]
    require(isinstance(slices, list) and 0 < len(slices) <= MAX_SLICES, "need 1 to 100 declared slices")
    require(sampling['alpha'] / len(slices) > 0, 'per-slice alpha underflows numeric precision')
    slice_ids = []
    total_cases = 0
    for sl in slices:
        fields(sl, ("id", "task", "role", "condition", "axis", "case_ids", "contract_sha256",
                    "horizon_steps", "required", "parent_exposure", "update_exposure"), label="slice")
        slice_ids.append(identifier(sl["id"], "slice.id"))
        identifier(sl["task"], "slice.task")
        text(sl["condition"], "condition")
        require(sl["axis"] in ("nominal", "camera", "layout", "lighting", "object", "language", "dynamics", "embodiment"), "unknown condition axis")
        require(sl["role"] in ROLES, "unknown task role")
        require(type(sl["required"]) is bool, "slice.required must be Boolean")
        sha(sl["contract_sha256"], "slice contract")
        integer(sl["horizon_steps"], "horizon_steps", 1, 100000)
        cases = sl["case_ids"]
        require(isinstance(cases, list) and 0 < len(cases) <= MAX_CASES, "need 1 to 1000 case IDs per slice")
        total_cases += len(cases)
        require(total_cases <= MAX_TOTAL_CASES, 'comparison exceeds the 10000 total slice-case preview limit')
        for case in cases:
            identifier(case, "case ID")
        require(len(set(cases)) == len(cases), "duplicate declared case IDs")
        for name in ("parent_exposure", "update_exposure"):
            require(sl[name] in ("included", "excluded", "unknown"), "unknown exposure status")
        if sl["role"].startswith("old_"):
            require(sl["parent_exposure"] == "included", "old task needs declared parent exposure")
            expected = "included" if sl["role"] == "old_rehearsed" else "excluded"
            require(sl["update_exposure"] == expected, "old-task role contradicts update exposure")
        if sl["role"] == "adaptation_target":
            require(sl["update_exposure"] == "included", "adaptation target must be included in update exposure")
        if sl["role"] == "held_out":
            require(sl["update_exposure"] == "excluded" and sl["parent_exposure"] != "included",
                    "held-out role conflicts with known parent/update exposure")
    require(len(set(slice_ids)) == len(slice_ids), "duplicate slice IDs")
    require(any(sl["required"] for sl in slices), "at least one slice must be required")
    return manifest


def _optional_number(value, label, integral=False):
    if value == "" or value is None:
        return None
    if integral:
        require(type(value) is int or (isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value)), f"{label} must be a nonnegative integer")
        return integer(int(value), label, 0, 100000000)
    require(type(value) in (int, float, str), f"{label} must be numeric")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise EvidenceError(f"invalid {label}") from exc
    require(math.isfinite(number) and 0 <= number <= 1e9, f"{label} must be finite and nonnegative")
    return number


def _validate_row(raw, policies, slices):
    fields(raw, COLUMNS, label="episode row")
    row = dict(raw)
    for key in ("revision", "slice", "case"):
        identifier(row[key], key)
    require(row["revision"] in policies, "undeclared revision")
    require(row["slice"] in slices, "undeclared slice")
    sl = slices[row["slice"]]
    require(row["case"] in sl["case_ids"], "undeclared case ID")
    require(row["status"] in STATUSES, "unknown terminal status")
    if row["status"] in OUTCOMES:
        require(type(row["success"]) is bool or (isinstance(row["success"], str) and row["success"] in ("0", "1", "true", "false")), "outcome success must be an explicit Boolean or 0/1/true/false")
        row["success"] = row["success"] is True or row["success"] in ("1", "true")
        require(row["status"] != "policy_failure" or not row["success"], "policy_failure cannot be successful")
    else:
        require(row["success"] is None or row["success"] == "", "infrastructure/interrupted records cannot carry scored success")
        row["success"] = None
    for field, expected in (("checkpoint_sha256", policies[row["revision"]]["checkpoint_sha256"]),
                            ("contract_sha256", sl["contract_sha256"])):
        if row["status"] in OUTCOMES or row[field] not in ("", None):
            require(sha(row[field], field) == expected, f"{field} disagrees with declared revision/slice")
    for field in ("physical_state_sha256", "rng_sha256"):
        if row["status"] in OUTCOMES or row[field] not in ("", None):
            sha(row[field], field)
    row["steps"] = _optional_number(row["steps"], "steps", integral=True)
    row["wall_seconds"] = _optional_number(row["wall_seconds"], "wall_seconds")
    require(row["steps"] is None or row["steps"] <= sl["horizon_steps"], "steps exceed the declared slice horizon")
    ref = row["evidence_ref"]
    require(isinstance(ref, str), "evidence_ref must be a relative path string or empty")
    if ref:
        text(ref, "evidence_ref", 512)
        require(not PurePosixPath(ref).is_absolute() and ".." not in PurePosixPath(ref).parts
                and ":" not in ref and "\\" not in ref, "evidence_ref must be a contained relative reference, not a URL")
    return row


def validate_rows(manifest, rows, *, max_errors=None):
    """Never return a partial table. Optional diagnostics collect one error per bad record."""
    require(isinstance(rows, list), "rows must be a list")
    if max_errors is not None:
        integer(max_errors, "max_errors", 1, 100)
    policies = {r["id"]: r for r in revisions(manifest)}
    slices = {sl["id"]: sl for sl in manifest["slices"]}
    require(len(rows) <= sum(len(sl["case_ids"]) for sl in slices.values()) * len(policies), "too many rows")
    table, errors, error_count = {}, [], 0
    for index, raw in enumerate(rows, 1):
        try:
            row = _validate_row(raw, policies, slices)
            key = row["revision"], row["slice"], row["case"]
            require(key not in table, f"duplicate episode: {key}")
            table[key] = row
        except EvidenceError as exc:
            location = {"record": index}
            if isinstance(raw, dict):
                for name in ("revision", "slice", "case"):
                    value = raw.get(name)
                    if isinstance(value, str) and len(value) <= 80 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
                        location[name] = value
            message = f"episode record {index}: {exc}"
            if max_errors is None:
                raise EvidenceError(message, details=location) from exc
            error_count += 1
            if len(errors) < max_errors:
                errors.append(dict(location, error=message))
    if error_count:
        message = errors[0]['error'] if error_count == 1 else f"{error_count} invalid episode records"
        raise EvidenceError(message, details={
            "input_valid": False, "error_count": error_count, "errors": errors,
            "errors_truncated": error_count > len(errors), "pairing_checks": "skipped"})
    for sl in slices.values():
        seen_physical = set()
        for case in sl["case_ids"]:
            records = [table[rid, sl["id"], case] for rid in policies if (rid, sl["id"], case) in table]
            for field in ("physical_state_sha256", "rng_sha256"):
                values = {row[field] for row in records if row[field] not in ("", None)}
                require(len(values) <= 1, f"paired {field} mismatch in {sl['id']}/{case}")
            physical_hashes = {row["physical_state_sha256"] for row in records if row["physical_state_sha256"] not in ("", None)}
            for physical in physical_hashes:
                require(physical not in seen_physical, f"aliased physical starts in {sl['id']}; repeated trials need a different sampling protocol")
                seen_physical.add(physical)
    return table
