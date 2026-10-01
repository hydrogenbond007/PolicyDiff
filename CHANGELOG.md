# Changelog

## 0.1.0.dev10 — unreleased

- Separate Linux process supervision from evaluation planning/orchestration;
  move shared ABI/source/runtime identity into the existing input module. The
  worker no longer imports the orchestrator or report-writing modules.
- Preserve lifecycle implementation and add fresh-interpreter dependency-boundary
  tests plus direct process-inventory/signal-guard tests.
- Fix baseline competence diagnostics when candidate or baseline outcomes are
  missing. Missing evidence still blocks inference; paired counts, eligibility
  decisions, statistical calculations and public schemas are unchanged.
- No backend registry, new dependency, hardware support or automatic recovery.

## 0.1.0.dev9 — unreleased

- Weight-only evaluation compares canonical JSON adapter options, rejecting
  Boolean/numeric type and signed-zero changes previously hidden by Python
  equality. Object-key reordering remains accepted.
- Preserve confirmed step counts when grading fails or is cancelled; keep the
  outcome unknown. Distinguish grading and final-bookkeeping diagnostics from
  environment-step and trace-write faults.
- Add planning/CLI and worker fault-injection regressions; document partial
  trace and elapsed-time semantics. No new dependency, schema or inference change.

## 0.1.0.dev8 — unreleased

- Native Claude Opus 5 source review of the pending executor and CLI/inspection
  integrations; scoped fixes and local verification are recorded in RELEASE_REVIEW.
- Preserve worker process-group ownership through cleanup; optional execution now
  requires Linux with waitid/WNOWAIT and readable /proc. Analysis stays portable.
- Retain receipt diagnostics alongside supervisor faults; evidence-integrity aborts
  remain aborts even when an exception has an empty message.
- External-log error counters no longer imply empty score records. Terminal logs
  receive an appropriate accounting note; documented CLI/API boundaries clarified.
- No change to comparison schemas, statistics, model compatibility or robot claims.

## 0.1.0.dev7 — unreleased

- Versioned, bounded worker receipts bind plan bytes, cell and unique admission.
  Validate transport/endpoint semantics; preserve valid terminals through final-
  record damage, refuse contradictory evidence and retain unscored worker faults.
- Full scoped LIBERO source/asset inventories include additions and outer package
  initializers. Execute checked adapter source without stale bytecode; use private
  worker cache prefixes and verify selected inputs again at seal time.
- Checkpoint measured outcomes before potentially slow sealing. Pending/failed
  seals block comparisons without erasing those outcomes.
- Atomic individual progress/receipt/summary publication and explicit admissions.
  No automatic recovery/resume, cross-file transaction or power-loss guarantee.
- Main-thread CLI SIGTERM cleanup, spawn-failure accounting and post-exit log/runtime
  checks. Separate complete outcome coverage from clean execution; lifecycle faults
  return exit 3 even with all outcomes present. Comparison schema/statistics unchanged.

## 0.1.0.dev6 — unreleased

- Offline `catalog` and `list_tasks` expose 130 pinned LIBERO task names, suite/query
  selection, source-order IDs and explicit unverified readiness/exposure labels.
- Opt-in `evaluate` integrates selected tasks/starts with a trusted local Python
  adapter in an existing LIBERO environment. Explicit Panda RGB/proprioception/
  OSC7 ABI; no arbitrary checkpoint, remote server or hardware support.
- Frozen task/source/asset/runner/checkpoint identities, per-case seeds, fresh
  worker groups, measured reset checks before candidate/retest actions, partial
  accounting and automatic comparison bundles. No retries, clipping or inference.
- Cancellation and cleanup cannot fabricate a horizon failure or erase a saved
  terminal outcome. Infrastructure faults stop further admissions.
- Analysis schemas, pairing/statistics and bundle formats remain unchanged.
  Standard-library analysis/catalogue remains independent of optional simulation.

## 0.1.0.dev5 — unreleased

- Read-only `inspect-log --format inspect-robots` and `inspect_log` API inventory
  selected external-log v1 fields: declared versus recorded counts, per-scorer
  denominators, empty epochs, annotation missingness and in-progress accounting.
- Missing annotations and absent error counters remain unknown. Zero/fractional
  scores are counted as recorded scores, never inferred as task outcomes.
- Explicit format/version, bounded arrays/scorers, finite numeric scores and
  exact input-byte hashes; no metadata traversal, sidecar reads or dependencies.
- This is not an automatic importer, pairing check or readiness certificate.
  The outcome schema, comparison engine, inference and bundle format are unchanged.

## 0.1.0.dev4 — unreleased

- Separate read-only `inspect-contract` command and `describe_contract_change`
  API for bounded protocol-description snapshots: recorded changes, explicit
  unknowns, absent fields and exact source-byte hashes.
- Flags the same declared contract digest with changed description text for
  review, without claiming proven drift, comparability or causality.
- No change to the v1 outcome manifest, pairing, statistics or bundle formats.
  No new runtime dependency, robot execution or model integration.
- Snapshot errors identify the failing side. Release checks verify every
  inventoried source's bytes in the sdist, not only one legacy test-file sentinel.

## 0.1.0.dev3 — unreleased

- Located input errors: record IDs and ending physical CSV lines, bounded and
  escaped unknown-field diagnostics, without changing validated evidence.
- `validate --max-errors` collects one error per rejected record, counts all
  rejected records and explicitly skips pairing checks until row errors are fixed.
  The Python comparison API remains fail-fast; errors gain additive `details`.
- Read-only `cases` command selects lost/gained/unresolved or other transitions
  while retaining all slice summaries, full denominators, source hashes and
  inference limits. Display filtering never changes the statistical population.
- No input/report/bundle schema change, new runtime dependency or robot run.

## 0.1.0.dev2 — unreleased

- Read-only `verify --bundle` command for payload/receipt consistency, with
  explicit no-authentication/no-reanalysis scope and bundle schema version 1.
- Atomic completion-marker publication, short-write detection, fixed snapshot
  names, matching read/write size limits and structured post-completion output errors.
- Regular-file input checks, finite JSON float parsing and digest-safe Markdown.
- Consolidated case pairing/classification without changing inference or reports;
  new permutation, mutation, arm-symmetry and adversarial bundle tests.
- Older unversioned receipts require regeneration from preserved inputs into a
  new directory. No old evidence is changed and no robot episode is rerun.
- Full source-inventory checks reject silently omitted files; bounded packaging
  commands preserve partial timeout logs. Installed checks include bundle verification.

## 0.1.0.dev1 — unreleased

GitHub-preview review hardening:

- Exhaustive three-arm terminal-state coverage and row-order invariance tests;
  explicit import prerequisites and competing-workflow limitations.
- Full-retest/gapped-partner tests, exact retest output-key guard, corrected CSV
  field count and explicit separate-endpoint error-control caveat in reports.
- Separate report/input schema versions and identical top-level library/CLI shape;
  a single package-version source now drives installation metadata and reports.
- Explicit unknown/incomplete retest evidence; complete-population retest
  discordance is null until all declared pairs are available.
- Stable zero-valued status categories, bounded Markdown details and parser limits.
- Valid large synthetic fixtures, readable apostrophes/status text and render-before-
  create output handling. Full case evidence remains in JSON and source snapshots.
- Source-distribution/installed-wheel verification and pinned, read-only GitHub CI.
- `Private :: Do Not Upload` prevents accidental package-index publication while
  package-index publication and licensing remain undecided.

## 0.1.0.dev0 — unreleased

Initial import-oriented developer preview:

- Parent/candidate comparison with optional unchanged-baseline retest.
- Strict manifest/CSV validation and exact input-byte snapshots.
- Per-condition outcomes, lost/gained cases, missingness and retest churn.
- Descriptive reporting by default; bounded, caller-attested fixed-report
  retention statistics when the declared evidence is eligible.
- JSON/Markdown bundles, explicit CLI exit semantics and synthetic walkthrough.
- Adversarial tests, portable packaging checks and a prepared GitHub CI workflow.

At dev0: not a robot runner, hardware adapter, deployment gate, causal diagnosis tool,
generalization certificate or stable public API. No public release has been made.
