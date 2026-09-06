# PolicyDiff

**What did this robot-policy update improve, what did it break, and what have we not tested?**

PolicyDiff is a local-first developer preview for comparing saved episode outcomes
before and after a policy update. It produces a condition-by-condition behavioral
diff, not a public leaderboard or a deployment certificate.

The initial workflow is deliberately narrow: one baseline, its candidate revision,
and an optional unchanged-baseline retest. Import a manifest and episode CSV;
receive a portable JSON report, a readable Markdown report, and exact input
snapshots with hashes. Nothing calls a model, runs a robot, or contacts a server.

## Try it

Python 3.10+; runtime uses only the standard library. From this directory:

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

PYTHONPATH=src python3 -m policydiff compare \
  --manifest demo-output/manifest.input.json \
  --episodes demo-output/episodes.input.csv \
  --output another-new-report

PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Or install with `pip install .` and use the `policydiff` command. Installing from
source requires setuptools 68+ and wheel in the build environment; runtime has
no third-party dependencies. The command refuses an existing output directory.
Without `--output`, `compare` writes JSON to standard output.

`verify` is read-only: it checks the four saved payloads against the completion
receipt and checks their linked metadata. This catches incomplete copies,
accidental edits and mismatched files. It does not rerun the comparison, inspect
evidence references, authenticate the author or prove any robot episode happened.
Coordinated rewrites of files and receipt can pass. Extra files in the directory
are outside the check. Use `validate` for the input contract and `compare` to
reanalyze saved inputs; neither runs a robot.

## What the first version does

- Separates old/rehearsed, old/unrehearsed, adaptation-target and held-out slices.
- Shows exact matched cases lost and gained, including when averages are unchanged.
- Keeps each declared camera, layout, object or other condition visible, even if
  it has no results. An axis label is not proof the corresponding test happened.
- Distinguishes scored policy failures from infrastructure faults, interruptions
  and missing records. Reports planned counts and asymmetric outcome coverage.
- Checks that caller-declared checkpoint, protocol, physical-start and RNG
  identities agree with the comparison contract; it does not inspect those assets.
- Shows unchanged-policy retest churn separately. It does not censor that churn
  or subtract it as a supposed causal correction.
- Snapshots exactly the bytes parsed, rejects ambiguous inputs, escapes report
  text and records bundle hashes. Caller-provided identity is still an attestation.

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
checkpoint verification need an adapter; they are not implemented here.

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

The broader category is not unoccupied: [RoboLens](https://www.robolens.to/)
advertises policy-regression and release workflows, while
[Inspect Robots](https://github.com/robocurve/inspect-robots) provides an evaluation
runner/logging framework. Those descriptions are not independently tested
integrations. PolicyDiff is a small analysis layer; superiority over those tools
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
| 0 | Command succeeded (validate, compare, demo or verify); **not** a policy pass |
| 2 | Invalid input or output error |
| 3 | `--strict-coverage` was requested and required coverage is incomplete |
| 4 | Internal software error; not an input rejection or policy failure |

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

No simulator runners, real-hardware pairing, model-specific adapters, dataset
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
