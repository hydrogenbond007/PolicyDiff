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
**all 13 column keys**, including optional measurements/references. Absent optional
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

## Output bundle

`manifest.input.json` and `episodes.input.csv` preserve exact source bytes.
`report.json` contains the validated comparison, full manifest, all case outcomes,
missingness, statistics/reasons withheld, and input hashes. `report.md` is the
readable counterpart. `COMPLETE.json`, written last, contains package version and
SHA-256 of the four files. No timestamp is injected, so identical inputs/version
on the same Python/platform produce identical output bytes. Floating-point
math libraries can differ across platforms; cross-platform byte identity is not
promised and confidence bounds are not rounded to manufacture that guarantee.
A failed write may leave a partial directory;
absence of `COMPLETE.json` means the bundle is unfinished. This marker is not a
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

Coverage counts always contain `complete`, `incomplete`, and `not_tested`;
terminal-status counts contain all four status keys, including measured zeros.
An untested declared retest is explicitly `coverage: not_tested`, and its complete-
population discordance in the inference object is `null`. Partial retests also
yield `null` there; their observed counts still carry paired/declared denominators.

The standalone report summarizes validated pairing but does not retain every
per-row identity digest. Rechecking identity requires `episodes.input.csv` and
the manifest snapshots in the CLI bundle, or the original input rows for a library
consumer. A digest alone would not supply missing identity evidence.
