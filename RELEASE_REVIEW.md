# GitHub-preview architecture and code review

Scope: the first analysis-only developer preview. Three new Claude Code Opus
source-inspection passes covered architecture, adversarial code behavior and
patch closure before release preparation. Their resolved model was Claude Opus 5. Reviewers did
not execute tests; all executions below are local operator checks.

## Architecture decisions

- Accepted separate input/report schema versions, consistent library/CLI report
  keys and a single source for the package version.
- Documented the full 13-key Python row contract and explicit module boundaries.
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
GitHub repository/visibility and license remain user decisions. Hosted CI cannot
be claimed passing before a push and an actual completed workflow.
