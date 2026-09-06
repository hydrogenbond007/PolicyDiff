# PolicyDiff developer preview — implementation contract

Local-first, standard-library Python package. No hosted services, robot execution,
model calls or external data access in the package. Input: a JSON comparison
manifest and CSV episode records. Output: JSON and Markdown behavioral-diff report.
Examples are explicitly synthetic, not robotics results. No license selected yet.

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

Commands implemented: validate, compare, demo and verify. Public Python compare(manifest, rows)
API shares the same validation. Package must install and run offline in an isolated
venv. Start with an import-oriented preview, not fake support for arbitrary VLAs.

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
| `bundle` | Exclusive snapshots, atomic completion and read-only checksum/metadata checks | Authenticate the author, rerun policy outcomes or follow evidence references |
| `cli` | Compose file input, comparison and exclusive bundle output | Publish, upload or issue a deployment pass |

The supported Python API is `compare` and `EvidenceError`. Other modules are
internal during the preview. Adapters should construct the explicit manifest/row
contract or use CLI input files, not couple policy execution into the engine.
No plugin loader is justified yet. A future runner needs its own measured-state,
budget, retest, intervention and evidence-capture contract; adding an enum alone
does not establish hardware support or valid repeated-trial inference.

Report and manifest schema versions are independent. The library always emits a
producer and nullable source inputs, and the CLI fills source hashes. Versioning
uses one literal source in `_version.py`; release checks compare it with installed
metadata. Same-build/interpreter/platform byte reproducibility is tested, not
asserted across different floating-point libraries or unpublished code revisions.
