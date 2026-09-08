# Development and contributions

This is a pre-alpha analysis library with optional local simulation. No PolicyDiff license or external
contribution terms have been chosen yet; resolve those before soliciting patches
from other people. The instructions below describe local development.

## Checks

Python 3.10+ and the standard library are sufficient for source tests:

```sh
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

For the packaging smoke test, first provide setuptools 68+, wheel and pip in your
development environment. Then:

```sh
python3 scripts/check_release.py --output release-check
```

This builds a source distribution and wheel, installs the wheel in a new isolated
environment, runs the tests against the installed package, checks CLI behavior,
compares deterministic bundles and verifies bundle hashes. Build/install commands
use `--no-index` and no dependency resolution. Bootstrap of build tools or Python
itself is separate and can require network access. Use a new output directory for
each run; existing outputs are never overwritten.

The checker inventories the complete source tree first and rejects unsupported
files instead of silently omitting them from its clean copy. New package assets,
documentation locations or workflow suffixes need an explicit release-recipe
update and tests. Known generated/local directories and the exact current output
directory are excluded, not audited; see the short exclusion list in the script.
It rechecks inventory and bytes at the end and preserves partial timeout logs.
This verifies the controlled clean-source recipe, not arbitrary dirty-tree
`pip install .` behavior or the contents of excluded directories. Audit the Git
staging list against the checked source hashes before publishing.

The GitHub workflow runs source tests and the packaging check on Python 3.10 and
3.12. CI success verifies software, not robot-policy competence or readiness.
Actions are pinned to verified full commit IDs and the workflow has read-only
repository permission, following [GitHub's workflow security guidance](https://docs.github.com/en/actions/reference/security/secure-use).
Check the actual commit's [GitHub Actions results](https://github.com/hydrogenbond007/PolicyDiff/actions);
local tests or a review summary do not establish that hosted CI passed.

## Contribution boundaries

- Add a failing adversarial test before fixing evidence-accounting bugs.
- Keep parsing/snapshotting, contract validation, comparison, statistics and
  rendering separate. Supported Python exports are documented in ARCHITECTURE.md;
  the opt-in executor is a separate CLI workflow, not part of the comparison engine.
- Keep runtime dependencies empty unless a concrete adapter requirement justifies
  a separately scoped optional dependency.
- Keep simulator controls outside the standard-library test gate. A listed task,
  mocked environment or successful action replay is not trained-policy validation.
- Preserve missingness and retest churn. Do not convert a lack of evidence into a
  pass, repair scored policy responses, or hide unfavorable cases.
- Use synthetic fixtures only in this repository. No credentials, checkpoints,
  private robot data, customer observations, private review transcripts or videos.
- Do not add upload behavior, external model calls or publication to the core.
- Document schema/output changes in the changelog. Pre-alpha does not imply a
  stable schema; consumers must check versions and tolerate explicit unsupported
  input errors, never guess around them.

## Before publication

Confirm repository visibility and choose a license; audit the staged file list
and archives; configure a private vulnerability-reporting channel; verify CI on
the actual GitHub repository. Do not push generated `release-check` directories.

Software checks can be completed locally while publication is blocked, but do not
call the project publicly released or production-ready until these separate
decisions/checks are complete. Repository access alone is not a license grant.
