# Scripted gripper\-fault demonstration

Evidence: **simulation** · Change: system

This report is not a deployment or safety certificate.

Observed changes: **1 lost / 0 gained / 0 unresolved** across 1 declared slice-cases; 1 paired outcomes. 0 slices eligible for retention inference. These totals are not independent pooled trials.

Comparing **baseline → candidate**. Unchanged retest: retest.

## Changes by condition

| Slice | Coverage | Paired success, before → after | Lost / gained | Retest churn lost / gained | Inference |
| --- | --- | --- | --- | --- | --- |
| libero\_spatial\.0 | complete | 1/1 → 0/1; 1 planned | 1 / 0 | 0 / 0 (1/1 pairs) | descriptive\_only |

Counts above describe observed pairs. Missing and non-outcome records remain below.

## libero\_spatial\.0

Task: libero\_spatial\.0 · Role: old\_rehearsed · Condition: pick up the black bowl between the plate and the ramekin and place it on the plate

Exposure: not\_a\_held\_out\_test; upstream: unknown.

- baseline: 1 successes / 1 scored outcomes; 1 expected; statuses completed 1; missing 0.
- candidate: 0 successes / 1 scored outcomes; 1 expected; statuses completed 1; missing 0.
- retest: 1 successes / 1 scored outcomes; 1 expected; statuses completed 1; missing 0.

Outcome coverage: 1 both; 0 before only; 0 after only; 0 neither.

Unchanged retest: 0 losses / 0 gains over 1 paired outcomes / 1 planned. This is not a causal correction.

Formal inference withheld: IID paired sampling was not attested.

steps: paired mean 260 → 1e+03; 1 measured pairs / 1 outcome pairs. Descriptive only; missing measurements and failure/stop censoring may bias this.

wall\_seconds: paired mean 5.75 → 21.4; 1 measured pairs / 1 outcome pairs. Descriptive only; missing measurements and failure/stop censoring may bias this.

| Case | Change | Candidate record | Evidence reference (unverified) |
| --- | --- | --- | --- |
| init\-0 | lost | completed | trials/0001/supervisor\_result\.json |

## Limits

- This is an evidence report, not a safety certificate or permission to deploy\.
- Caller\-supplied hashes/exposure labels do not prove physical execution, training history or IID sampling\.
- Paired flips can reflect stochastic variability; retest churn is descriptive and is not subtracted as a causal correction\.
- Inference covers this fixed, declared slice family only; not repeated releases, adaptive selection or sequential peeking\.
- Alpha correction is separate for regression tests and harmful\-flip bounds, not a joint guarantee across both endpoint families\.
- Incomplete\-pair summaries describe observed subsets; they do not estimate the full declared population\.
- Held\-out status is relative to declared data; unknown upstream pretraining is not proof of novelty\.
- No inference about untested objects, tasks, embodiments or sim\-to\-real transfer follows\.
- Evidence references are unverified local references; this package never opens or executes them\.
- The v1 endpoint is the supplied Boolean task outcome under each slice contract; no stable\-success inference from truncated traces\.

## Input snapshots

- manifest\_sha256: `4d4457921bdd62eb62a01ceea4055f6f1140768edb795d7df26f8a33ffaec34e`
- episodes\_sha256: `9e0911eeb1b8d3998e1d151a32c54a9acc56d1a7a997824b54a11e8e3dbe77e0`
