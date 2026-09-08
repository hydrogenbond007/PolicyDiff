# Schema v1 guide

All fields are required unless marked optional; unknown fields are rejected.
The generated demo is the executable example.

The input manifest uses `schema_version`. Output reports independently use
`report_schema_version` and echo `input_schema_version`. Library and CLI reports
always include `producer` and `inputs`; the in-memory API has `inputs: null`
because it did not parse source files. File-oriented commands fill those hashes.

## Manifest

- `schema_version`: integer 1.
- `title`: short printable text.
- `evidence_origin`: `synthetic` or `simulation`. Hardware is unsupported.
- `baseline`, `candidate`, optional `retest`: objects with unique `id`, `family`
  and lowercase `checkpoint_sha256`. Candidate must also name baseline ID as
  `parent`. One declared family only. Retest must match baseline checkpoint.
- `change`: `kind` (`weights`, `context`, `system`), `description`, and
  `upstream_exposure` (`documented` or `unknown`). Weights must change checkpoint
  bytes; context/system-only comparisons must retain them. This labels the
  comparison, not an independently verified causal intervention.
- `sampling`: `design` (`fixed_cases` or `iid_pairs`), Boolean
  `frozen_before_outcomes`, `alpha`, `maximum_harm_probability`, and
  `minimum_baseline_success_rate`. Probabilities must be finite and strictly
  between zero and one. These are caller declarations, not proof of independence
  or preregistration. Prespecify them; do not tune thresholds after seeing results.
- `slices`: 1–100 objects described below. At least one must be required.

## Slice

- `id`, `task`: printable identifiers, using letters/numbers/underscore/dash/dot.
- `role`: `old_rehearsed`, `old_unrehearsed`, `adaptation_target`, or `held_out`.
- `condition`: human-readable test condition.
- `axis`: `nominal`, `camera`, `layout`, `lighting`, `object`, `language`,
  `dynamics`, or `embodiment`. Describes the tested variation, not supported robots.
- `case_ids`: 1–1000 distinct identifiers in planned order. Do not drop failed or
  unexecuted cases from this list. A repeated physical start under a different
  case ID within a slice is rejected; repeated/clustered trials need a different protocol.
- `contract_sha256`: digest of the shared execution/evaluation contract for this
  slice: environment/version, controller, sensors, budgets/horizon, stop rule,
  success rule and pairing protocol. All arms in this slice must agree. Conditions
  in different slices may have different contracts.
- `horizon_steps`: positive integer, at most 100000.
- `required`: Boolean, used by coverage checks, **not** multiplicity selection.
- `parent_exposure`, `update_exposure`: `included`, `excluded`, or `unknown` for
  this task-condition slice. Old roles require parent included; rehearsed update
  included and unrehearsed update excluded. Adaptation target requires update
  included. Held-out requires update excluded and parent excluded or unknown.
  Unknown parent or upstream exposure must never be called proved novel.

The contract covers shared evaluation machinery. A deliberate system/context
change must be described separately; an accidental evaluator/controller mismatch
must not be hidden by assigning both arms the same digest. V1 does not hash or
verify the changed system configuration. Mixed weight-and-system changes are not
supported. For a weight-only claim, preserve the remaining configuration.

## Episode CSV

Exactly these columns, in any order, once each:

```text
revision,slice,case,status,success,checkpoint_sha256,contract_sha256,physical_state_sha256,rng_sha256,steps,wall_seconds,evidence_ref
```

For `compare(manifest, rows)`, `rows` is a list of dictionaries, each containing
**all 12 column keys**, including optional measurements/references. Absent optional
numbers may be `None` or `""`; references use `""`. Actual Python Booleans are
accepted for success, integers for steps, and finite numbers for wall time.
No fields are silently defaulted. `manifest` is a dictionary with the shape above.

- `revision`, `slice`, `case`: declared IDs, unique as a triple.
- `status`: `completed`, `policy_failure`, `infrastructure_error`, `interrupted`.
- `success`: `0`, `1`, `false` or `true` for scored outcomes; Python API also
  accepts actual Booleans. Policy failure must be false. Infrastructure error
  or interruption must be blank (`None` also allowed through Python).
- `checkpoint_sha256`, `contract_sha256`: required for scored outcomes and must
  match the declared revision/slice. Non-outcomes may leave these blank.
- `physical_state_sha256`, `rng_sha256`: required for scored outcomes; exact
  agreement across scored arms of a case. Hash physical start separately from RNG
  identity; include all relevant simulator state in a canonical representation.
  A runner may identify RNG by a saved state or an explicit seeded schedule; the
  execution contract must specify which representation and its completeness.
  A seed-schedule digest is not a recorded RNG-state snapshot. Do not replace a
  missing identity with a hash of a case ID or an unrelated constant.
  Same seed/hash does not guarantee deterministic outcome; preserve retest churn.
  Nonblank identities on non-outcome records must also agree; known physical
  aliases are rejected even if one case has no scored outcome.
- `steps`, `wall_seconds`: optional nonnegative metrics. Steps are integral and
  cannot exceed the slice horizon. Nonfinite values are rejected.
- `evidence_ref`: optional printable contained relative path. No URL, absolute
  path, backslash or `..` traversal. It is not opened or verified.

Missing rows remain missing. Do not convert crashes into failures or silently retry
policy failures. `completed,false` and `policy_failure,false` are both scored
failures but remain separate status categories. Records are caller-classified;
the package cannot validate whether that classification was experimentally correct.

## Validation diagnostics

`validate --max-errors N` collects one error per rejected record (default 20,
range 1–100 displayed errors). It scans every parsed record, returning exit 2
and JSON on standard error with `input_valid: false`, `error_count`, `errors`,
`errors_truncated` and `pairing_checks: skipped` when any are rejected. Each
diagnostic includes `record` (1-based, excluding the header), `csv_line_end`
(the ending physical CSV line), an `error` message, and well-formed
`revision`/`slice`/`case` IDs when available. Invalid cell contents are not echoed.
Treat identifiers and paths as potentially confidential even in diagnostics.

The limit bounds displayed diagnostics, not scanning. Only the first detected
error per record is counted; repairing it may reveal another. Duplicate triples
among otherwise valid rows are rejected. Duplicate checks do not use rejected
rows; fixing an earlier bad record can therefore also
reveal a duplicate on another record. Cross-arm identity and physical-start
alias checks run only after all rows pass; these checks still fail fast. Parsing,
manifest and population-limit failures also fail fast, without an `errors` list.
A malformed CSV record can have a location even when parsing stops. No invalid
input produces a comparison or a partial table. There is no auto-repair mode.

`compare` remains fail-fast, adding location details for rejected records. The
Python API raises `EvidenceError` (still a `ValueError`) with a readable message
and additive `details` dictionary; it has record numbers but no file line mapping.
Diagnostics do not alter report/input schema versions or validated evidence.

## Output bundle

`manifest.input.json` and `episodes.input.csv` preserve exact source bytes.
`report.json` contains the validated comparison, full manifest, all case outcomes,
missingness, statistics/reasons withheld, and input hashes. `report.md` is the
readable counterpart. `COMPLETE.json`, written last, contains package version and
SHA-256 of the four files and `bundle_schema_version: 1`. No timestamp is injected, so identical inputs/version
on the same Python/platform produce identical output bytes. Floating-point
math libraries can differ across platforms; cross-platform byte identity is not
promised and confidence bounds are not rounded to manufacture that guarantee.
A failed write may leave a partial directory. The receipt is written and closed
as `COMPLETE.json.tmp`, then atomically renamed to `COMPLETE.json`. No incomplete
receipt is deliberately published under the final name; the temporary file and
partial payloads are preserved on failure. Consumers must parse/check the receipt,
not treat mere file presence as proof of completion. Atomic publication is not
a power-loss durability guarantee (there is no filesystem `fsync` protocol), a
signed attestation or a guarantee against later modification.
The completion marker also includes evidence origin, coverage, descriptive totals
and input hashes. "Complete" describes writing the bundle, not passing the tests.

Input files have a 16 MiB limit each. Outputs must be new directories. Preserve
private data and handle release/publication separately from report generation.
There are at most 10000 declared slice-cases total and 30000 CSV rows; CSV rows
are bounded during parsing, before comparison. JSON retains all declared cases;
Markdown shows at most 50 changed/unresolved cases and 10 missing-ID examples
per slice, with explicit notices pointing to the complete JSON. Input limits do
not imply equally small outputs or protection against hostile local workloads.

## Case selection view

`cases --manifest FILE --episodes FILE` validates and analyzes the full inputs,
then selects cases for display. It does not read an existing report or bypass
validation of rows outside the filter. Optional repeatable `--slice ID` and
`--transition NAME` select the displayed cases; transitions are `lost`, `gained`,
`unresolved` (the defaults), `retained_success` and `shared_failure`. Unknown or
duplicate filter values are rejected. `--limit` is a global display cap, 1–10000,
default 100. Results preserve declared slice/case order, not severity ranking.

The JSON view has `case_view_schema_version: 1`, `status: cases_selected`,
`comparison` (full report-level summaries, source hashes and limitations),
`slices` (every declared slice's unfiltered evidence and inference, plus
`selected_for_display`, `matching_cases`, `shown_cases`), `selection` (normalized
filters, limit, matching/shown/omitted counts, `truncated`) and `cases` (selected
case records with their slice IDs). The full manifest remains in the input;
this projection is not a replacement evidence bundle. Copying only `cases`
discards context. An empty selection is not proof of no regressions elsewhere.
The case-view version governs the selection metadata and wrapping structure;
inherited comparison, slice and case-record fields follow
`comparison.report_schema_version`. Consumers must check both versions. The
`comparison` object is a summary projection, not a full report with a manifest.

Filtering changes no denominator, alpha correction, inference or strict-coverage
decision. All these refer to the full declared comparison. This is exploratory
triage, not an outcome-selected confirmatory test or release gate. Exit 3 with
`--strict-coverage` still emits the view when required full coverage is incomplete.

## Read-only bundle checks

`verify --bundle DIRECTORY` supports bundle schema 1, input schema 1 and report
schema 1. It checks the fixed four payload filenames, SHA-256 values, producer
identity, receipt/report summary links, report/snapshot input hashes and embedded
manifest equality. JSON duplicate keys, nonfinite numbers (including exponent
overflow), unsupported schemas and symlinked/nonregular payload files are rejected.
Receipt size is limited to 64 KiB; each other bundle file is limited to 64 MiB.
The writer enforces matching limits and requires the two exact input snapshots.

Success is `bundle_consistent`, not a policy pass, authentication or a reanalysis
of task outcomes. The verifier does not recompute statistics, validate CSV episode
records, open evidence references or inspect additional files. Anyone able to
replace files and their receipt together can construct a passing bundle. Use
`validate` for input-schema checks and `compare` for a fresh analysis under the
installed version; cross-version/cross-platform report-byte equality is not assumed.

Older unversioned developer-preview receipts are rejected, not silently upgraded.
Their preserved inputs can be passed to `compare` with a new output directory;
the resulting bundle records the current producer version. Original evidence
is not overwritten and no policy episode is rerun. `input_sha256` remains the
receipt's field name; `inputs` is the corresponding report field.

Coverage counts always contain `complete`, `incomplete`, and `not_tested`;
terminal-status counts contain all four status keys, including measured zeros.
An untested declared retest is explicitly `coverage: not_tested`, and its complete-
population discordance in the inference object is `null`. Partial retests also
yield `null` there; their observed counts still carry paired/declared denominators.

The standalone report summarizes validated pairing but does not retain every
per-row identity digest. Rechecking identity requires `episodes.input.csv` and
the manifest snapshots in the CLI bundle, or the original input rows for a library
consumer. A digest alone would not supply missing identity evidence.

`unchanged_retest.coverage` describes baseline-to-retest **pair** coverage, not
just execution of the retest arm. A fully scored retest can still lack paired
baseline outcomes; per-arm counts are in `revisions[<retest_id>].scored_outcomes`.

`family_alpha` is corrected across all declared slices separately for each
endpoint family: regression tests and harmful-flip upper bounds. It does not
provide a joint error guarantee across both, nor over repeated reports or releases.

## Protocol description snapshots

This is a **separate descriptive format**, not a new manifest version or an input
to `compare`/`verify`. It helps review recorded setup differences across runs.
Nothing establishes that a snapshot is complete, accurate or associated with an
executed run. The Python API is `describe_contract_change(before, after)`;
`inspect-contract --before FILE --after FILE` reads files and writes JSON to stdout.

Each snapshot has exactly four required fields:

- `contract_snapshot_schema_version`: integer 1 (not Boolean or float).
- `label`: 1–160 printable characters, no surrounding whitespace.
- `declared_for_contract_sha256`: lowercase SHA-256 or `null` when no association
  is recorded. This digest is **caller-declared**, not checked or recomputed.
- `fields`: object with 1–64 caller-named entries. Names use the same 1–80-character
  identifier alphabet as slice IDs; dots can express a flat namespace. Each entry
  has exactly `status` and `value`. Status `recorded` requires a 1–200-character
  printable string with no surrounding whitespace; `unrecorded` requires `null`.

Unknown envelope/entry keys, non-string recorded values and nested structures
are rejected. File input is bounded to 64 KiB per snapshot and parsed with the
same duplicate-key, UTF-8 and finite-number checks as other JSON inputs. Counts,
names and values are bounded in the Python API too; only byte-oriented limits
and source-byte hashes apply specifically to file inputs.
This is a short-description format, not a lossless raw-configuration export.
Empty/multiline values are unsupported; do not silently replace them with invented
text. A separately named source-byte fingerprint field can record their identity,
but cannot explain their contents. As with existing input readers, a regular file
reached through a symlink is accepted; this is not hostile-filesystem race protection.

Two executable **synthetic** examples, saved as `before.json` and `after.json`:

```json
{
  "contract_snapshot_schema_version": 1,
  "label": "Synthetic before",
  "declared_for_contract_sha256": null,
  "fields": {
    "budget.wall_seconds": {"status": "recorded", "value": "600"},
    "controller.kind": {"status": "recorded", "value": "waypoint"},
    "success.post_release": {"status": "unrecorded", "value": null}
  }
}
```

```json
{
  "contract_snapshot_schema_version": 1,
  "label": "Synthetic after",
  "declared_for_contract_sha256": null,
  "fields": {
    "budget.wall_seconds": {"status": "recorded", "value": "3600"},
    "controller.kind": {"status": "recorded", "value": "waypoint"},
    "success.post_release": {"status": "unrecorded", "value": null}
  }
}
```

These produce one `changed`, one `same` and one `undetermined` field. Values use
literal string equality: `20` and `20.0` differ; units are not converted. Normalize
units and naming in the exporter, consistently and without inventing missing
values. A field present on one side only is undetermined, **not** a known added or
removed setting. Renaming a key creates two undetermined entries, not an inferred
mapping. Fields omitted from both inputs are invisible. Use explicit `unrecorded`
entries to make known gaps visible; a small all-same snapshot proves no completeness.

Suggested names (not enforced): `environment.version`, `task_set`,
`controller.kind`, `controller.control_hz`, `action.interface`, `sensors.views`,
`budget.physics_steps`, `budget.wall_seconds`, `agent.history`, `agent.effort`,
`success.rule`, `termination.rule`, `interruption.rule`, `pairing.method`.
Record only what the source supports. Do not label a release/source-file hash as
the execution-contract digest unless that is actually its recorded meaning.
Deliberate model/context interventions are separate from the shared execution
contract; this utility does not decide which settings belong to either category.

Output uses `contract_change_schema_version: 1` and status
`contract_descriptions_compared`. It includes:

- `producer`; `inputs` with exact `before_snapshot_sha256`/`after_snapshot_sha256`
  for the CLI, or `null` for the in-memory API; `snapshots` with each side's label,
  input schema version and declared contract association.
- `counts` with all three keys (`same`, `changed`, `undetermined`),
  `any_declared_field_changed`, `any_field_undetermined`, and `fields` containing
  the entire sorted union (up to 128 entries). Each has `name`, comparison `status`,
  and `before`/`after` entries. Missing entries are explicitly rendered with
  `status: absent, value: null`; explicit unknowns retain `status: unrecorded`.
- `declared_digest_relation`: `same`, `different` or `undetermined` (either digest
  is null). `same_declared_digest_with_field_changes` is true only for two equal
  non-null declared digests and at least one changed recorded string. It requests
  review, not a finding of actual drift: descriptions may differ without the
  underlying settings differing, or the association may be wrong. Absent/unrecorded
  entries do not set this signal; inspect the undetermined counts separately.
- Non-optional `limitations`, including for an all-same result. No statistical
  population, outcome, physical-validity claim or comparability verdict is produced.

Both snapshots must validate before output. Exit 0 means successful description,
even if fields changed or are undetermined; invalid input/I/O returns exit 2, with
JSON on stderr when it is writable. Errors identify `snapshot_side` (`before` or
`after`), including schema and size failures. Python `EvidenceError.details` also
identifies the side. Unexpected internal errors exit 4. There is no output directory,
bundle, overwrite, strict-coverage mode or automatic gate. Parser usage errors
retain the normal argparse usage/exit-2 behavior. Output failures retain completed
command context through the usual CLI diagnostics.

Preserve the original snapshots if you need to reproduce the view. Its byte hashes
identify those snapshots, **not** the actual robot setup. Snapshot labels, field
names and values may be confidential; nothing is redacted automatically. An
optional sidecar next to a report bundle stays outside `verify`'s four-file check.

## External-log inventory

`inspect-log --format inspect-robots --input run.json` and
`inspect_log(log, source_format="inspect-robots")` provide an independent,
descriptive inventory. The explicit format selects an adapter for the public
[Inspect Robots v1 log structure](https://github.com/robocurve/inspect-robots/blob/7e4d1b7aee1c0d3cfc3a05a7492b9d12cda666f9/src/inspect_robots/log.py).
It is not auto-detection, full upstream-schema validation or an outcome importer.
Only integer source version 1 is supported; future versions fail closed.

Inspected structure:

- Root `status` is `started`, `success`, `error` or `cancelled`; `eval` and
  `results` are objects and `samples` is an array of at most 1,000 scenes.
- `results.total_scenes` and `total_trials` are bounded nonnegative integers.
  `errored_trials` is optional: absent means unknown, not zero; explicit null
  or a malformed number is rejected.
- Scenes require distinct nonempty printable `scene_id` strings without surrounding
  whitespace (up to512 characters), execution status, and `epochs` arrays. Across all scenes there
  may be at most30,000 recorded epochs and100 distinct epoch-scorer names.
- Each epoch is a dictionary of at most100 named finite numeric scores. Zero,
  fractional and negative scores remain recorded scores. Booleans, strings and
  nonfinite numbers are rejected. Optional `reduced`/`metrics` dictionaries get
  the same numeric shape checks but are not used to reconstruct trial outcomes.
  Scorer names are nonempty printable strings up to200 characters without
  surrounding whitespace.
- Optional `operator_judgements`, `judgement_sources` and `termination_reasons`
  must be empty arrays (legacy representation) or parallel to epochs. Entries
  are null or nonempty printable strings up to200 characters; values/sources
  are not assigned outcome semantics. Surrounding whitespace, explicit null arrays
  and misalignment fail.
- Optional `policy_config`, `embodiment_info` and `scene_metadata` must be objects;
  optional `trial_metadata` must be empty or a parallel array of objects. Their
  contents are opaque. Other fields, including other annotation arrays, are not
  validated, followed or echoed. Additional upstream fields do not imply support.

Output uses `log_inspection_schema_version: 1`, status `log_inspected`, and
`comparison_support: not_established` on every successful inventory. It includes:

- Producer/version, selected source format/version and run execution status.
  `inputs.log_sha256` hashes the exact CLI input bytes; in-memory API `inputs`
  is null. The CLI uses the existing16MiB, UTF-8, duplicate-key/depth/nonfinite
  JSON rejection path and reads only the explicitly selected file.
- `declared_counts` retains counters as recorded. `observed_counts` counts scene,
  epoch, nonempty/scored-epoch and empty-epoch records, plus epochs with a score
  named `operator` but no recorded non-null operator judgement. That last count
  is an annotation gap, not proof of grader failure or a new policy failure.
  These count score **records in this snapshot**, not whether trials were graded:
  the pinned upstream live writer leaves even completed epochs' scores empty.
- `scorers` has a sorted union of epoch scorer names, each with its scored-epoch
  count and `epochs_without_score` across **all recorded epochs**, including empty
  ones. No success rate, thresholding or reduction is performed.
- `accounting` labels the run `in_progress` or `terminal` and reports declared
  scene/trial count discrepancies and error counts exceeding declared trials or
  empty epochs. These labels reflect the recorded status, not current process
  liveness or assurance that every planned trial finished. It never corrects the
  counters. An active live epoch may legitimately
  precede the completed-trial count; empty epochs need not all be errors. These
  checks are not exhaustive integrity validation or population reconstruction.
- `annotation_coverage` counts non-null and unannotated epochs for each inspected
  annotation. `scenes` preserves source order,0-based indices and IDs, execution
  status, score/empty counts, per-array state/entry/null counts and metadata presence.
  An absent array, an explicit empty array and an aligned all-null array stay
  distinct. Unannotated epochs combine unavailable and explicitly null entries;
  their separate representation remains in each scene's annotation details.
- `identity_presence` describes selected `/eval` fields as absent, null, empty
  or recorded. This checks presence, not type validity, truth or sufficiency.
  Metadata presence is not a search for checkpoint/reset/RNG evidence. Fields
  inside opaque metadata may contain such evidence; it is not assessed here.
- Non-optional limitations: execution success is not task success, planned or
  never-started trials cannot be inferred, and no physical validity, pairing,
  independence, deployment verdict or comparison is established.

The CLI emits JSON to stdout and creates no bundle. Exit0 means the inventory
completed even with accounting differences; invalid selected fields or I/O use
exit2, unexpected internal errors exit4. Normal argparse usage errors remain2.
There is no strict-readiness flag, directory crawl, migration, sidecar discovery,
metadata-value display or upstream-code execution. Preserve the original input
if you need to reproduce the report. IDs and scorer names may themselves be
sensitive; output is not an anonymization guarantee.
