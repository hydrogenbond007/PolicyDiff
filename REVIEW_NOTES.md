# Developer-preview review log

Latest continuation: see the dev3 section of [release review](RELEASE_REVIEW.md)
for three additional actual Opus 5 passes, diagnostic/triage changes and their
adjudication. The initial implementation record below is historical.

Three substantive Claude Code reviews have been received: contract review,
implementation review and patch-closure review. All used the signed-in Claude subscription, requested
Opus, and resolved to Claude Opus 5. Only this new framework's source and docs were
shared. The reviewers inspected inline source; they did **not** execute tests.
An earlier response that merely promised inspection is not counted as a review.
Local test execution is separate evidence, not model approval.

## Accepted and implemented

- Declared versus observed pair counts and asymmetric missingness partition.
- Caller-declared baseline competence threshold; all declared slices remain in
  the fixed multiplicity denominator, including optional/untested slices.
- Exact-byte snapshots; the demo also parses its serialized inputs before comparison.
- Top-level losses/gains/unresolved counts and inference eligibility. No eligible
  slices yields `has_inferential_regression: null`, not a reassuring false.
- Retest fields explicitly named `churn_losses`, `churn_gains`, `retest_successes`;
  retest discordance accompanies the inference object and summary table.
- Markdown includes coverage asymmetry, retest warning and censored metric means.
- Known physical-start aliases/mismatches are rejected on non-outcome rows too.
- Internal CLI defects have separate `internal_error` / exit 4 classification.
- Bundle completion receipts carry origin, coverage, input hashes and totals.
- Returned manifest is copied to prevent later caller mutation changing provenance.

Local adversarial tests additionally exposed a Boolean/integer cache-key collision
in the statistics helpers. Typed caches and explicit argument validation fixed it.

The closure reviewer confirmed the above patches on source inspection and found
one numerical edge case: a tiny alpha divided across slices could underflow to
zero and be misclassified as an internal error. Validation and a regression test
now reject it as input. This fix was independently being made locally when the
review arrived. A documentation ambiguity about aliases was also clarified:
the prohibition is within each slice, not across all slices. The closure review
predates those two small final edits; they have local test coverage, not a further
Claude sign-off. Local suite: 79 tests on Python 3.10 and 3.12.

## Recommendations deliberately not adopted

- **Reject equal-hash retest outcome churn:** that would censor nondeterminism.
  Equal declared starts/seeds do not prove complete deterministic execution.
  Preserve and flag observed churn; do not subtract it or infer causality from it.
- **Reject any empty required slice as invalid input:** this would prevent a useful
  missing-evidence report. Keep the slice visible and withhold inference;
  `--strict-coverage` supplies an explicit workflow failure.
- **Stamp the command name into otherwise identical bundles:** evidence origin is
  recorded everywhere relevant. Exact-input compare and demo bundles remain byte-
  reproducible; origin describes the evidence, not which entry point serialized it.

These are engineering review outcomes, not certification of scientific readiness,
safe robot behavior, novelty, independence, or commercial defensibility.
