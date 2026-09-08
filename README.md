# PolicyDiff

**What did this robot-policy update improve, what did it break, and what have we not tested?**

PolicyDiff is a local-first developer preview for testing and comparing robot-policy
updates. It produces a condition-by-condition behavioral diff, not a public
leaderboard or a deployment certificate.

The initial workflow is deliberately narrow: one baseline, its candidate revision,
and an optional unchanged-baseline retest. Import a manifest and episode CSV;
receive a portable JSON report, a readable Markdown report, and exact input
snapshots with hashes. These comparison commands never execute a policy. An opt-in
LIBERO task catalogue and local runner now provide an integrated simulation path
for an explicitly compatible Python policy adapter; see [execution guide](EXECUTION.md).

## Try it

Python 3.10+; analysis and catalogue use only the standard library. From this directory:

```sh
PYTHONPATH=src python3 -m policydiff demo --output demo-output
```

Open `demo-output/report.md`. The demo is **entirely synthetic**. It includes an
unchanged aggregate score hiding different lost/gained cases, a camera-condition
regression, an adaptation gain, unknown exposure, an interruption, and an untested
condition. Those are software examples, not evidence about real robot policies.
The demo deliberately withholds inference; numerical unit tests exercise that
branch without presenting synthetic fixtures as measured simulation results.

```sh
PYTHONPATH=src python3 -m policydiff validate \
  --manifest demo-output/manifest.input.json \
  --episodes demo-output/episodes.input.csv

PYTHONPATH=src python3 -m policydiff verify --bundle demo-output

PYTHONPATH=src python3 -m policydiff cases \
  --manifest demo-output/manifest.input.json \
  --episodes demo-output/episodes.input.csv \
  --slice old-camera --transition lost --limit 10

PYTHONPATH=src python3 -m policydiff compare \
  --manifest demo-output/manifest.input.json \
  --episodes demo-output/episodes.input.csv \
  --output another-new-report

PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Or install with `pip install .` and use the `policydiff` command. Installing from
source requires setuptools 68+ and wheel in the build environment; runtime has
no mandatory third-party dependencies. The optional executor requires a separately
prepared LIBERO environment. Commands refuse an existing output directory.
Without `--output`, `compare` writes JSON to standard output.

`verify` is read-only: it checks the four saved payloads against the completion
receipt and checks their linked metadata. This catches incomplete copies,
accidental edits and mismatched files. It does not rerun the comparison, inspect
evidence references, authenticate the author or prove any robot episode happened.
Coordinated rewrites of files and receipt can pass. Extra files in the directory
are outside the check. Use `validate` for the input contract and `compare` to
reanalyze saved inputs; neither runs a robot.

`cases` writes a focused JSON view to standard output. By default it lists lost,
gained and unresolved cases; repeat `--slice` or `--transition` to select several.
The default limit is 100 displayed cases, with exact matching/shown/omitted counts.
All slice summaries, full-population counts and inference limits stay visible,
even when only losses in one slice are selected. Filtering never recomputes
statistics on the chosen outcomes. Unknown filters fail instead of returning a
misleading empty result. This command validates and compares the entire supplied
manifest/CSV first; it does not trust an existing `report.json` or open traces.
Each invocation repeats that full analysis, even when only a display filter changes.

## What the first version does

- Lists 130 source-pinned LIBERO tasks by suite or search text, without importing a simulator.
- Optionally runs selected tasks/starts against baseline, candidate and retest,
  then produces the same comparison bundle. Requires a compatible trusted adapter;
  catalogue listing alone never means a task or checkpoint has been validated.
- Separates old/rehearsed, old/unrehearsed, adaptation-target and held-out slices.
- Shows exact matched cases lost and gained, including when averages are unchanged.
- Keeps each declared camera, layout, object or other condition visible, even if
  it has no results. An axis label is not proof the corresponding test happened.
- Distinguishes scored policy failures from infrastructure faults, interruptions
  and missing records. Reports planned counts and asymmetric outcome coverage.
- Checks that caller-declared checkpoint, protocol, physical-start and RNG
  identities agree with the comparison contract. Imported CSV identities remain
  caller assertions; the opt-in runner separately captures its documented input/reset hashes.
- Shows unchanged-policy retest churn separately. It does not censor that churn
  or subtract it as a supposed causal correction.
- Snapshots exactly the bytes parsed, rejects ambiguous inputs, escapes report
  text and records bundle hashes. Caller-provided identity is still an attestation.

## Choose tasks and run a policy update

```sh
policydiff catalog --suite libero_object
policydiff catalog --query drawer
policydiff evaluate --config evaluation.json --output new-evaluation --allow-local-code
```

The [execution guide](EXECUTION.md) defines the configuration and adapter contract.
Select explicit task IDs, initial-state indices, budgets and known training-exposure
labels. The runner freezes these inputs, measures starts before policy execution,
runs fresh worker processes and records losses, gains, retest churn and missingness.

This first integration supports **LIBERO + Panda + one explicit RGB/proprioception
and seven-action interface**, not any checkpoint on any robot. You supply model
loading and its training-matched preprocessing. No automatic downloads, model
servers, real hardware or multi-benchmark catalogue yet. The command executes
trusted local code and is not a security sandbox. Its reports are descriptive,
not an automated release gate. Listed tasks are not a competence claim.

## Did the test setup change too?

Before attributing a score difference to a policy, inspect the recorded protocol
descriptions. `inspect-contract` is a separate, read-only command:

```sh
policydiff inspect-contract --before before.json --after after.json
```

Use the two synthetic snapshot examples in [the schema guide](SCHEMA.md#protocol-description-snapshots).
The command shows `same`, `changed` and `undetermined` fields, keeps absent and
explicitly unrecorded values distinct, and hashes the exact input bytes. A changed
description under the same declared contract digest is flagged for review. This
can catch a recordkeeping inconsistency; it cannot establish which record is right.

Keep controller/action interface, sensors, budgets, history/reasoning and scoring
rules visible across runs. Field names are yours, not tied to a robot/model. Values
are short literal strings, not arbitrary nested configs. Matching descriptions
do **not** prove matching protocols: fields omitted from both inputs are invisible.
The command never reads outcomes, changes the score-comparison gate or supplies a
pass/fail judgment. Exit 0 means the description command completed, even with changes.

## What does an existing runner log actually contain?

For an Inspect Robots JSON log, use the independent read-only inventory command:

```sh
policydiff inspect-log --format inspect-robots --input run.json
```

It reports declared counters beside recorded epochs, per-scorer coverage, missing
grading annotations and accounting differences. A zero score stays a score; an
empty epoch does not become a policy failure or proof that grading never happened.
The upstream live writer leaves score records empty even for completed trials;
its active epoch can also precede the completed-trial counter. Recorded status
does not prove the process is still running. Missing, empty and all-null annotation
arrays remain distinguishable.

This is **not an importer or a readiness verdict**. It does not infer binary
success, compare policies or manufacture checkpoint/reset/RNG identities from
names and seeds. Metadata contents, instructions, transcripts and sidecars are
not read or echoed; scene IDs and scorer names are included and may be sensitive.
Unknown fields remain uninspected. See [format and limits](SCHEMA.md#external-log-inventory).
No Inspect Robots installation or network connection is needed. Exit 0 means the
inventory completed, including when accounting differences or missing data exist.

## Input contract

The demo generates a complete manifest and the CSV header. See
[the schema guide](SCHEMA.md) for field semantics and
[the architecture contract](ARCHITECTURE.md) for scope.

In Python:

```python
from policydiff import compare

report = compare(manifest, rows)
for condition in report["slices"]:
    print(condition["id"], condition["observed_pairs"], condition["coverage"])
```

The library validates data but does not read files or compute source-byte hashes;
the file-oriented CLI adds input hashes and snapshots. Evidence references are
unverified relative-path text, not clickable/executed assets. Video, trace and
checkpoint verification are outside the comparison API. The opt-in executor
captures selected file/reset identities but does not authenticate arbitrary evidence.

## Is this a fit for your workflow?

Use it when you already have saved, exactly paired simulation outcomes for a
policy and its update, and want a reviewable accounting of losses, gains and
missing evidence. A short paired-join script can reproduce the basic counts.
The additional utility here is the shared input contract, rejection checks,
explicit uncertainty and portable evidence bundle—not novel statistics.

To bring your own runs:

1. Declare the baseline, update, planned cases and conditions in the manifest.
   Preserve failed and unexecuted cases; do not build the population from successes.
2. Export the schema's 12 CSV columns from your runner. Use actual recorded start,
   checkpoint and execution identities. If they were not captured, this preview
   cannot certify pairing; do not manufacture hashes from case IDs to get accepted.
3. Run `validate`, then `compare`. Read coverage and lost/gained cases before
   inference. A retest is optional for descriptive reporting, required for inference.

There is no automatic importer yet. Unknown training exposure, mixed updates,
repeated starts and real hardware can fall outside this contract; see the schema
before investing in an export. This does not audit the runner or its success labels.

### Debug an export

`validate` reports the first error in each rejected episode record, with the
1-based record number, its ending physical CSV line and any well-formed case IDs.
It scans all records but displays at most 20 diagnostics; use `--max-errors 5`
to change that limit (1–100). `error_count` counts rejected records, not every
possible defect. `errors_truncated` makes omitted diagnostics explicit. No values
are repaired and no partial comparison is produced.

Manifest/CSV parsing errors stop immediately. If episode records are invalid,
cross-arm identity and physical-alias checks are explicitly `pairing_checks:
skipped`; fix the records and validate again. `compare` and the Python API remain
fail-fast. Record numbers exclude the header; CSV lines can differ because quoted
fields may span lines. See [diagnostic semantics](SCHEMA.md#validation-diagnostics).

The broader category is not unoccupied: [RoboLens](https://www.robolens.to/)
advertises policy-regression and release workflows, while
[Inspect Robots](https://github.com/robocurve/inspect-robots) provides an evaluation
runner/logging framework. Those descriptions are not independently tested
integrations. PolicyDiff is a small analysis layer with an experimental local runner;
superiority over those tools
or an existing team notebook has not been demonstrated.

## Statistical scope

Default: descriptive counts only. Formal *retention* inference is available only
for old-task slices with complete baseline/candidate/retest outcomes, a caller-
declared competent baseline, simulation evidence, an IID-pair sampling attestation
and a protocol declared frozen before outcomes. None of those attestations can
be independently proved from this CSV.

For eligible slices, the report gives a one-sided exact paired sign/McNemar test
for more losses than gains, and a one-sided Clopper–Pearson upper bound on the
probability of a **baseline-success/candidate-failure pair**. That probability is
unconditional over the declared paired-case population, not conditional on
baseline success. Alpha is divided across **all declared slices**, including
optional and untested ones. Each statistic family has that correction separately;
there is no joint guarantee over both endpoints, repeated releases, adaptive
selection, clustered samples or sequential peeking.

`within_declared_harm_bound` means only that this bounded endpoint cleared the
caller-declared threshold under those assumptions. It does not mean zero damage,
safety, generalization, causally attributable forgetting or permission to deploy.
`inconclusive` is not evidence of preservation. Step/time means are descriptive
and may be biased by stopping, failure censoring and missing measurements.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Command succeeded; **not** a policy pass |
| 2 | Invalid input/output, or `evaluate` aborted on evidence-integrity failure |
| 3 | Required coverage is incomplete under `--strict-coverage`, or `evaluate` is incomplete/unclean |
| 4 | Internal software error; not an input rejection or policy failure |

Parser-detected usage errors (missing flags, malformed values or invalid choices)
also exit 2, but print usage text rather than JSON. Do not assume every exit-2
response is machine-readable diagnostics.
An integrity-aborted `evaluate` prints `status: evaluation_aborted` and its error
on standard output, saves `evaluation.json`, and creates no comparison bundle.

An incomplete report is useful evidence and is still written with strict coverage.
An output error can also occur **after** a bundle finished, for example when a
downstream command closes its input pipe. That returns exit 2 with
`output_notification_failed`, `bundle_status: complete` and the output path on
standard error. Do not automatically delete or overwrite outputs after any error;
inspect them with `verify` first.
Other completed commands report their `command` and `result_status` on delivery
failure. If standard error is also unavailable, diagnostics are best-effort; the
documented exit code is still preserved.
Retest is optional to declare, but once declared it participates in coverage:
`--strict-coverage` requires its outcomes as well as baseline/candidate outcomes
on each required slice. Partial retests are preserved and reported as incomplete.
There is deliberately no automatic performance release gate yet.
The summary always shows observed losses, gains and unresolved slice-cases.
`has_inferential_regression: null` means **not assessed**, not no regression.
`false` means no eligible slice met the regression criterion; it still does not
mean preservation. Check eligibility, coverage and observed losses separately.

## Not built yet

No simulator integrations beyond the experimental LIBERO runner, real-hardware
pairing, model-specific adapters, dataset
exposure verifier, failure-video UI, causal failure classifier, hosted service or
cross-embodiment transfer claim. The initial CSV schema supports exact paired
synthetic/simulation evidence only. Context changes are not weight fine-tuning.

This is an early local build, not a proven moat or a production replacement for
another platform. The next product test is whether teams can use it to catch
consequential regressions on real policy updates more reliably or cheaply than
their existing workflow.

## Distribution

No open-source license has been selected and there is no public package release.
This developer preview is maintained in the owner's
[PolicyDiff repository](https://github.com/hydrogenbond007/PolicyDiff). Private
repository access is not an open-source license. Choose licensing and contribution
terms before public distribution or soliciting external patches.

See [development and release checks](CONTRIBUTING.md), [security scope](SECURITY.md),
and [unreleased changes](CHANGELOG.md). Only synthetic examples belong in this
repository; generated reports can contain confidential source data.
