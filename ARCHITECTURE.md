# PolicyDiff developer preview — implementation contract

Local-first Python package with a standard-library analysis/catalogue core and a
separate opt-in LIBERO executor. Core input: JSON comparison manifest and CSV
episode records. Output: JSON and Markdown behavioral-diff report. The optional
executor invokes a trusted local adapter in a separately prepared environment;
it does not provide a model server or hardware stack. Repository examples are
synthetic, not robotics results. No PolicyDiff license selected yet; bundled
LIBERO task-name data retains its upstream MIT notice.

Manifest schema v1 has exactly one baseline, one candidate and optional unchanged
retest revision. Each carries id, checkpoint identity and model family; the
candidate names its parent. Update kind distinguishes weights, context and system.
The retest must have the same checkpoint identity as the baseline.

Each test slice has id, task, role (old_rehearsed, old_unrehearsed,
adaptation_target, held_out), condition, condition axis, expected case IDs,
execution-contract SHA-256, required flag and known exposure in parent/update.
Unmeasured slices are represented by empty/missing rows, never invented outcomes.
Different conditions may have different execution contracts; all compared arms
within a slice must share that slice's contract. Checkpoint identity is separate.
Upstream training exposure may be unknown and cannot be inferred by this software.

Rows identify revision, slice and case, status, Boolean success (or blank for
non-outcomes), physical-state hash, RNG digest, execution contract, revision
checkpoint hash, optional steps/wall seconds and local evidence reference.
The initial exact-pairing protocol supports synthetic/simulator evidence only;
real hardware and clustered repetitions are explicitly unsupported.
Statuses distinguish completed, policy_failure, infrastructure_error and
interrupted. Policy failures count as failure under this explicit schema;
infrastructure faults/interruption/missing rows never become successes or zeros.

Parser reads each input once, hashes those exact bytes, rejects duplicate JSON
keys, NaN, malformed rows, unknown fields/identities and contradictory metadata.
Do not treat falsey non-object metadata as absent. Output directories are new and
exclusive, never overwrite inputs. Report contains source hashes, package version,
full manifest and all non-outcome counts. Markdown escapes untrusted text.

Per slice: paired counts, harmful and helpful flips, missing/incomplete cells,
baseline/candidate absolute success counts, optional retest churn, steps and
time separately. Strong default is descriptive reporting. Formal fixed-report
one-sided paired tests require explicit IID sampling attestation AND complete
baseline/candidate/retest outcome coverage and competent baseline. Correct across
all declared slices, including empty ones. Missing evidence cannot produce a
preservation disposition. Retest churn is reported, not automatically subtracted
or treated as a statistical test proving causality.

Held-out labels require exclusion from the update and appropriate parent
exclusion or explicitly unknown provenance; report upstream uncertainty. Role
validation cannot prove training history. No generalization certificate, deployment
pass or automatic release gate. Untested slices stay visible. Partial paired
counts are observed subsets, not unconditional population estimates.

Commands implemented: validate, compare, cases, demo, verify, inspect-contract,
inspect-log, catalog and evaluate. Public Python compare(manifest, rows)
API shares the same validation. Package must install and run offline in an isolated
venv for analysis/catalogue. Execution dependencies are optional and not downloaded.

Top-level summaries expose lost/gained/unresolved slice-cases and eligibility.
No eligible tests means a null inferential-regression flag, not false. Retest
fields explicitly name churn, and churn context accompanies inference. Bundle
completion receipts identify evidence origin and coverage; completion is not a pass.

## Module and extension boundaries

| Component | Responsibility | Must not do |
| --- | --- | --- |
| `schema` | Validate declared identities, roles, population and records | Infer training exposure or repair scored records |
| `io` | Parse and hash exact snapshots with size/row limits | Execute evidence references |
| `engine` | Pair cases, report changes/coverage, determine inference eligibility | Run policies or silently impute missing results |
| `statistics` | Bounded numerical functions under caller-established assumptions | Decide experimental readiness |
| `report` | Escape and summarize Markdown with visible truncation | Invent or hide underlying JSON outcomes |
| `triage` | Select displayed cases from a full validated comparison, retaining all slice summaries | Recompute inference or coverage on outcome-selected cases |
| `contract` | Describe flat caller-recorded protocol fields across two snapshots | Certify matching protocols, interpret outcomes or weaken the comparison gate |
| `log_inspection` | Inventory selected external-runner counters, score and annotation coverage | Import outcomes, infer pairing, read metadata contents or declare readiness |
| `catalogue` / `_libero_tasks` | Filter pinned public task-name metadata with stable source-order IDs | Claim task readiness, training exclusion or model compatibility |
| `execution` | Freeze a bounded selection, supervise owned workers, persist partial evidence and call the existing comparison API | Invent outcomes, retry failures or bypass schema gates |
| `execution_inputs` | Inventory scoped local source/assets and load the checked adapter snapshot | Claim exhaustive dependency identity or run cached adapter bytecode |
| `execution_records` | Bind/validate worker receipts and atomically publish individual checkpoints | Authenticate workers, resolve contradictory outcomes by preference or promise multi-file durability |
| `_libero_worker` | Restore and fingerprint selected starts, enforce an explicit observation/action ABI, capture official success | Normalize/clip for an arbitrary model or certify exhaustive state identity |
| `bundle` | Exclusive snapshots, atomic completion and read-only checksum/metadata checks | Authenticate the author, rerun policy outcomes or follow evidence references |
| `cli` | Compose file input, comparison and exclusive bundle output | Publish, upload or issue a deployment pass |

The supported Python API is `compare`, `describe_contract_change`, `inspect_log`,
`list_tasks` and `EvidenceError`. Other modules are
internal during the preview. Adapters should construct the explicit manifest/row
contract or use CLI input files, not couple policy execution into the engine.
There is no plugin marketplace or automatic loader discovery. The opt-in CLI
loads exactly the caller-selected trusted Python adapter. Its narrow measured-state,
budget, retest and evidence-capture contract is in [EXECUTION.md](EXECUTION.md).
Adding catalogue names never establishes hardware support or valid inference.

Execution health is separate from outcome coverage. A valid endpoint can survive
cleanup damage, while conflicting receipts or failed/pending input seals block
the comparison. Receipt schema v1 binds plan hash, cell index and a unique local
admission ID; dev6's old unversioned worker artifacts are not silently upgraded.
Existing comparison v1 inputs/bundles remain readable. No automatic resume,
database, event-log reconstruction, security sandbox or hardware lifecycle claim.

`inspect_log(log, source_format="inspect-robots")` is isolated from the comparison
engine. It inventories selected v1 fields, preserving recorded denominators and
unknown annotations, not claiming full upstream-schema validation. The CLI hashes
one bounded JSON read; it follows no sidecars and emits no outcome manifest.
Source-specific shape checks stay in this module, not in the evidence schema.

Report and manifest schema versions are independent. The library always emits a
producer and nullable source inputs, and the CLI fills source hashes. Versioning
uses one literal source in `_version.py`; release checks compare it with installed
metadata. Same-build/interpreter/platform byte reproducibility is tested, not
asserted across different floating-point libraries or unpublished code revisions.

`validate` optionally collects bounded, located diagnostics through the same row
validator used by `compare`. Invalid rows never yield a partial table. Pairing
checks are explicitly skipped until rows pass. CSV line locations are separate
from evidence fields. `cases` runs the full comparison before display filtering;
its independently versioned view retains full-population inference and coverage.
The view envelope is versioned separately; inherited report fields still follow
the nested report schema version. On valid inputs `validate` deliberately runs
the shared row checks again through `compare`, trading duplicate work for no
prevalidated-table bypass of the public comparison contract.

`describe_contract_change(before, after)` is separate from scored comparisons.
Its closed snapshot envelope contains bounded, caller-named literal string fields;
unrecorded and absent entries remain undetermined. No nested diff, normalization,
ignored fields, patch output or runner hooks. Its optional declared digest is an
unverified association, never computed from description text. The CLI independently
hashes the exact snapshot bytes. Same declared digest plus changed text requests
review, not a claim of proven configuration drift. The v1 manifest, pairing,
inference and bundle formats do not ingest these snapshots. Keep them beside a
bundle if useful; `verify` neither includes nor checks such sidecar files.
