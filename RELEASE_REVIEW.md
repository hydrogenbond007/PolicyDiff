# GitHub-preview architecture and code review

Scope: the first analysis-only developer preview. Three new Claude Code Opus
source-inspection passes covered architecture, adversarial code behavior and
patch closure before release preparation. Their resolved model was Claude Opus 5. Reviewers did
not execute tests; all executions below are local operator checks.

This opening record is historical. Later version-specific reviews below describe
additional scope; in particular, dev6 introduces optional local simulation.

## Architecture decisions

- Accepted separate input/report schema versions, consistent library/CLI report
  keys and a single source for the package version.
- Documented the full 12-key Python row contract and explicit module boundaries.
- Preserved conservative coverage: a retest is optional to declare, but if declared
  must be complete for strict required coverage. This is now explicit in CLI/docs.
- Qualified byte determinism to the same build/interpreter/platform. Did not round
  confidence bounds downward, which could change a threshold decision.
- Kept qualified `policydiff.io` / `policydiff.statistics` modules: they do not shadow
  standard-library top-level imports in the supported installation layout.
- Rejected relabeling synthetic public demos as simulation to show inference. The
  inference and rendering branches are instead exercised by numerical unit tests.
  An architecture reviewer not receiving tests is not evidence those tests do not exist.
- Deferred plugin systems, runner integration and hardware support. Those are
  separate product work, not missing pieces to disguise in this package.

## Code findings fixed

- Fixture-generated step counts could exceed their declared horizon for larger n.
- Missing retests could expose zero discordance without an explicit completeness
  qualifier; incomplete populations now expose null in the inference context.
- Unbounded Markdown details amplified sparse inputs; details now have explicit
  caps, total declared cases are bounded, and CSV row limits apply while parsing.
- Rendering failures previously left an empty output directory; rendering now
  succeeds before the exclusive output directory is created.
- Apostrophes and raw status dictionaries were hard to read in Markdown.
- Sparse status/coverage categories now consistently include zero counts.
- Distribution contents and build-tool requirements were incomplete; added
  explicit packaging contents and clean-source/installed-wheel checks.

An aggregate identity hash was not substituted for evidence: the CLI bundle
retains exact manifest/CSV snapshots; standalone reports are summaries, not enough
to independently recheck per-row identity. Library consumers must retain inputs.
The documented test runner is standard-library unittest; pytest is not a required
dependency and compatibility with its optional modes is not claimed.

## Final closure disposition

The closure pass confirmed the core fixes above and identified additional release-
test gaps. Added direct installed console-script checks, assertions that tests use
installed package modules, explicit missing-release-file errors and bounded failure
diagnostics printed into CI logs. Test/package execution was then rerun locally.

The reviewer also identified files missing from its *review payload*: `__main__.py`,
the changelog and the prior review summary. They exist in the candidate; package
inventory and actual module-entry execution verify that fact. Review summaries
contain no raw transcripts, customer data or private run artifacts. Full prompts
and receipts remain outside the package. Action pins were independently checked
against the official release commits before the review; their SHA provenance is
not established by model inspection alone.

Archive hashes identify a particular build; only the report-bundle roundtrip is
tested for same-input determinism. Reproducible wheel/sdist byte hashes are not
claimed. No hosted workflow result or unconditional model "approval" is claimed.

## Release boundaries

Only synthetic examples belong in the repository. Private studies, weights,
raw review prompts/receipts and customer data remain outside it. Readiness here
means a software preview, not scientific replication, robot safety or a moat.
The user subsequently selected the repository; its existing private visibility
is preserved. Licensing remains undecided. Hosted CI must be checked against the
actual pushed commit, not inferred from these local review notes.

## First-push product challenge

A further Claude Opus source review challenged the preview against a short
paired-join notebook and adjacent regression platforms. Its useful scope today
is explicit evidence accounting and portable comparison bundles, not novel
statistics or a demonstrated business moat. Integration cost and repeat usage
remain unmeasured. The reviewer did not receive statistics or tests in this pass;
the focused follow-up code review did. A broader new code-review request timed
out without a verdict and is not counted as completed.

Accepted: fixed documentation incorrectly counting 13 rather than 12 CSV fields,
qualified identity checks as caller-declared consistency (not asset verification),
and documented import prerequisites and alternatives. `MAX_ROWS` is used in the
CSV parser and was not dead code. Kept synthetic demos descriptive; numerical
unit tests exercise inference. Did not weaken identity/replication rules or
select inferential slices after seeing outcomes to make more reports pass.

Next product falsifier, not a completed study: ask an external simulation-policy
team to compare two existing revisions against its normal notebook workflow.
Record missing source metadata, unassisted import/triage time, consequential
issues found and whether the team reuses the report for its next update. If
required evidence cannot be recovered or the tool adds no useful finding or time
saving, reconsider the contract/product before adding a platform.

## First-push focused code review

The further Claude Opus pairing/statistics review found no blocker in its inspected
scope, not an absence-of-bugs guarantee. Accepted an explicit full-retest/gapped-
partner test and an exact retest-output-key assertion. Kept the existing explicit
mapping of pair counts to retest churn; a second projection layer solely to rename
private helper keys would add code without fixing a current incorrect result.

The README already qualified error control separately for the two endpoint
families. That caveat now also travels in standalone JSON/Markdown reports and
the schema guide. No statistical threshold or eligibility gate was relaxed.

Independent local checks ran 100 unit tests, including all 216 three-arm terminal-
state combinations, and clean installed-package checks on Python 3.10 and 3.12.
A separate check against locally available SciPy covered 100 confidence bounds
and 20 paired tests; maximum absolute discrepancies were below 2e-13 and 5e-16,
respectively. SciPy is not a runtime or test-suite dependency. These are software
checks, not physical experiments or evidence of a commercial moat.

## dev2 public-readiness hardening

Two substantive Fable 5 source-review passes and an independent internal agent
reviewed the actual changes. Model identity was verified through the native
subscription response; reviews did not run robots or certify correctness.
Private prompts/receipts remain outside the repository.

Reproduced and fixed: creation of a torn final completion marker, unsafe snapshot
names in the internal writer, closed-pipe shutdown changing documented exit codes,
post-success output failures losing completion context, unguarded error reporting
when stderr is closed, malformed input-digest rendering, and overflowing JSON
numbers being classified as internal defects. Static nonregular input checks also
prevent accidentally blocking on named pipes. Short writes and failed atomic
renames preserve partial output without publishing the final completion marker.

The new `verify` command checks fixed payload bytes and linked metadata. It does
not recompute outcomes, authenticate provenance or resist coordinated rewrites;
tests demonstrate that limitation. Reanalysis is an explicit separate `compare`
operation, so verification does not assume cross-version/platform byte equality.
Kept the existing `input_sha256` receipt vocabulary and documented its mapping.
New bundle schema 1 makes legacy unversioned-marker rejection explicit.

The internal agent consolidated repeated case loops without changing report
schema or inference gates. Four additional invariants and 500 deterministic
synthetic old/new comparisons found equivalent reports. Added coverage for
baseline-gapped retest pairs, version disagreement and unknown receipt fields.

For release tooling, accepted fail-closed source inventory and preserved timeout
diagnostics. Kept controlled clean-source builds, an explicit generated-file
exclusion list, and the existing 120-second command cap; did not build from a dirty
workspace or silently inflate timeout limits. Excluded paths are not audited.

Concurrency races under hostile local filesystem mutation, power-loss durability,
cryptographic authentication, licensing and hosted CI are not established by these
changes. No gate was relaxed, unsupported robot mode added or scientific claim
expanded. The final local tests/installed checks are engineering evidence only.

## dev3 import diagnostics and case triage

Three additional native Claude Opus 5 source inspections covered design priority,
diagnostic implementation and triage/architecture/closure. Actual response model
identity was checked; the reviewers did not execute tests. Raw receipts and
payloads stay outside this repository. Recommendations were tested, not accepted
as automatic approval or evidence of a moat.

Accepted: locate rejected records, bound displayed diagnostics while counting
all rejected records, name unknown fields safely, and add a small case-selection
command. A malformed/oversize/multiline header was initially mislabelled as an
episode record; reproduced on Python 3.10 and 3.12, then fixed with an explicit
header-validation boundary. A claimed stale CSV line after blank rows did not
reproduce on either version: DictReader's fieldnames property refreshes it. An
explicit underlying-reader line reference now makes the intended meaning clearer,
but this is not counted as a reproduced bug fix.

Retest coverage remains pair coverage, not just retest-arm execution. Physical
aliases remain prohibited within a slice, not across different slice contracts.
These were already documented and tested; neither was changed to satisfy a review.

`cases` validates and analyzes all inputs before selecting displayed records.
Every slice summary, full-population denominator, inference result, coverage
decision and source hash is retained. Display limits expose matching/shown/omitted
counts, including when earlier cases consume the limit for a later slice. Invalid
unselected data still fails. No saved-report trust path, importer, ranking,
statistical feature or dependency was added. The view envelope and inherited
report fields have explicit separate version semantics.

Closure accepted documentation of argparse's non-JSON usage errors, full-analysis
cost on every invocation, and additional installed-command negative tests.
Validating twice for diagnostic collection is an acknowledged constant-factor
cost, not a reason to expose a prevalidated-table bypass. Further feature expansion
needs a demonstrated user workflow, not another generic platform narrative.

Local checks: the original 137 tests remain, with diagnostic/triage adversarial
coverage added; clean offline installed-package verification exercises module
and console commands on Python 3.10 and 3.12. A separate 200-comparison synthetic
differential check against installed dev2 found identical full reports after
normalizing only producer.version, including 40 synthetic inference-branch cases.
Those are software fixtures, not new simulator or hardware observations. Final
source inventory/hashes are checked again before the commit; hosted CI is separate.

## dev4 benchmark-informed protocol descriptions

Three further actual native Opus 5 source inspections covered architecture,
adversarial implementation and closure. Only scoped package source/docs/tests
were supplied, not private robotics payloads. An earlier connection timeout
returned no analysis and is not counted. Reviewer identity came from the native
response; ancillary native Haiku routing usage is not a substitute reviewer.
All reviews were source inspection, not test execution or certification.

Accepted the separate `describe_contract_change` API and `inspect-contract` CLI.
Descriptions stay outside the outcome manifest, inference and bundle gate. Field
names belong to exporters; flat, bounded strings avoid a general nested-JSON diff
framework. Absent and unrecorded are distinct, both undetermined. An equal declared
digest with changed text requests review, not proof of a configuration conflict:
wording can change without the underlying setup changing. Complete-looking
descriptions never certify complete or equivalent protocols.

Reproduced/fixed: validation and size errors did not identify which input was bad.
Both API and CLI now identify the before/after side. A metadata-orientation mutant
survived the initial new tests; distinct labels/digests and exact projection keys
now catch it. The review's separate suggestions that swapped field entries and an
extra `comparable` key escaped testing did not reproduce: existing tests rejected
both. Those are not claimed as runtime defects or new fixes. Removed unnecessary
deep copying of validated string/null entries and clarified standalone limitations.

Replaced a weak legacy-file sdist sentinel with complete inventoried-source hash
checks, including omitted/changed/nonregular/duplicate-member rejection tests.
The closure review's concern about omitted dotfiles was checked against the actual
MANIFEST and clean builds: required files were included. Retained the deliberately
small generated-file exclusion list; speculative cache types do not justify an
unbounded ignore mechanism. Excluded directories remain outside the source audit.

Closure found no blocker in the supplied source scope. After it, added exact
label/name-boundary and CLI metadata-orientation assertions, and normalized release
inventory keys to POSIX archive paths. Those final test/release-script edits are
operator-verified changes, not a further model sign-off. The library/CLI runtime
remains at the reviewed source revision. No Windows execution is claimed.

Software checks include source and clean installed-package tests on Python 3.10
and 3.12; 200 synthetic dev3/dev4 comparisons matched after normalizing only
producer.version, with 40 inference-branch fixtures. A separate private check of
preserved episode inputs retained legacy counts and caveats, with no robot rerun.
Partial source-bound historical configuration descriptions also exercised the
installed CLI; selected fields are not a complete protocol audit or causal study.
Examples in this repository remain synthetic. These checks establish engineering
behavior within their scope, not novelty, a defensible business moat or deployment
readiness. Native review payloads and validation artifacts stay outside the package.

## dev5 external-log inventory

An actual native Kimi design/test-planning pass and a native Claude Opus5
adversarial case-design pass examined public upstream schema/source only. Neither
received this implementation or executed tests. Private implementation review
remains pending payload clearance; these passes are not a code-review sign-off.
Native records, source pins and adjudication stay outside the package.

Accepted a separate read-only inventory, explicit format/version, bounded selected
fields, preserved absent/empty/null annotations, and score-record denominators.
Rejected JSONL/directory discovery, recursive metadata searches, readiness scores,
automatic imports and new exit-code semantics. This deliberately small helper
does not replace the upstream runner or establish comparison eligibility.

Claude identified that the upstream live writer leaves even completed epoch score
records empty. Reproduced with the actual pinned writer's callbacks on synthetic
records, then corrected the initial "unscored trial" wording: empty means no score
recorded in this snapshot, not proof that grading never happened. An active epoch
can precede the completed-trial counter; recorded `started` status is not current
process liveness. Missing annotations never become negative policy judgements.

Local checks cover fixed output shape, absence distinctions, numeric/array limits,
opaque metadata, exact hashes, output failure context, and200 seeded accounting
cases. Seven preserved upstream software-probe logs exercise the installed CLI;
five snapshots from actual upstream live-writer callbacks exercise source parsing.
These checks run no robot, policy, scorer or model. No recovery from logless trials,
physical pairing, full upstream-schema conformance or independent usability is
claimed. Source/installed tests and module/console commands are covered by the
offline release script; actual hosted CI remains separate.

## dev6 task catalogue and integrated execution

User direction expanded the product from importing outcomes to choosing tasks
and running compatible policies locally. Actual native Claude Opus5 and native
Kimi (requested managed k3 alias) completed public-only architecture challenges.
Neither received private implementation, benchmark data or weights. Those are
architecture reviews, not implementation approval. Private provider payload
clearance remains pending; local Codex adversarial review inspected the code.

Accepted a thin integration around existing LIBERO environment primitives,
source-pinned task identities, separate listed-versus-tested status, an explicit
observation/action ABI and caller-declared exposure. Model loading/normalization
stay in a trusted explicit adapter; arbitrary VLA compatibility is not inferred.
Rejected implicit action clipping and hiding changed outcomes inside a supposed
noise floor. Unchanged-policy retest churn remains evidence, not a correction.

Local adversarial review identified terminal-outcome loss during cleanup, surviving
same-group helpers, pairing checks deferred until after later trials, ragged-action
misclassification, missing dependency errors, and cancellation mislabeled as a
completed horizon failure. Fixes add pre-cleanup terminal records, owned-group
cleanup, pre-adapter measured-reset checks and incremental row validation,
explicit invalid-action handling and cancellation accounting. Runner source bytes
are included in the frozen identity, in addition to selected inputs/assets.

Standard-library tests cover mocked execution accounting and worker control flow,
real subprocess timeout/cancellation/helper cleanup, and catalogue purity. Separate
local simulator controls exercise saved action replay and deliberate no-ops; these
are integration checks, not learned-policy validation, transfer or competence
evidence. Raw controls and native review payloads remain outside the package.
The offline release script checks catalogue console/module parity and refusal of
untrusted/invalid evaluation configs without installing simulator dependencies.
Software/source receipts, not this narrative, identify each verified build.
