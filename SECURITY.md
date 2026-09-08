# Security scope

PolicyDiff is a local developer preview, not a hardened multi-tenant service.
Use it on files you are authorized to process. The core has no model calls,
network clients, shell execution or active report content. Evidence references
are inert text. Input hashes verify byte identity, not truth or authenticity.

Files must remain in operator-controlled directories during reads and writes.
The tool is not a defense against another local process replacing directories
or symlinks during execution. This includes `verify`: only check quiescent bundles
that another process is not modifying. Static nonregular input files and symlinked
bundle members are rejected, but pre-open checks are not a race-proof sandbox.
Do not expose its file-reading interface directly
to unauthenticated users or accept arbitrary server filesystem paths.

Input-size, row and case limits bound normal preview use; they are not a promise
of hardened availability under hostile workloads. Reports contain exact input
snapshots and may therefore contain confidential information. Local-only does
not make a generated report safe to publish.

Bundle verification checks accidental corruption and internal metadata links,
not authenticity, execution truth or correctness of the analysis. A coordinated
rewrite of payloads and the unsigned receipt can pass. It does not open referenced
traces/videos or certify extra files placed beside the four checked payloads.

## Optional trusted-code execution

The optional `evaluate --allow-local-code` command has a different trust boundary:
it executes the explicitly selected Python adapter and trusted checkpoint/initial-
state assets, including potentially pickle-based files. Dependencies must already
exist in the selected environment. Process groups and runtime/log caps manage
lifecycle, not hostile code. Adapters can access files/network or escape a process
group; do not accept adapters, checkpoints or LIBERO assets from untrusted users.
Input hashes detect ordinary changes but do not sandbox code, authenticate model
weights or exhaustively identify dependency/import state. Execution evidence may
contain paths, observations and user/model output. Nothing is automatically uploaded.

## Reporting issues

No private reporting channel has been configured yet. Before public release,
the maintainer must provide one (for example GitHub private vulnerability reporting).
Do not put credentials, customer data or sensitive exploit details in a public
issue. Ordinary reproducible bugs should use minimal synthetic fixtures.

There is no security-support SLA or claim of an external security audit. AI code
review and passing tests are engineering checks, not security certification.
