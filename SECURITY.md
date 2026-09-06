# Security scope

PolicyDiff is a local developer preview, not a hardened multi-tenant service.
Use it on files you are authorized to process. The core has no model calls,
network clients, shell execution or active report content. Evidence references
are inert text. Input hashes verify byte identity, not truth or authenticity.

Files must remain in operator-controlled directories during reads and writes.
The tool is not a defense against another local process replacing directories
or symlinks during execution. Do not expose its file-reading interface directly
to unauthenticated users or accept arbitrary server filesystem paths.

Input-size, row and case limits bound normal preview use; they are not a promise
of hardened availability under hostile workloads. Reports contain exact input
snapshots and may therefore contain confidential information. Local-only does
not make a generated report safe to publish.

## Reporting issues

No private reporting channel has been configured yet. Before public release,
the maintainer must provide one (for example GitHub private vulnerability reporting).
Do not put credentials, customer data or sensitive exploit details in a public
issue. Ordinary reproducible bugs should use minimal synthetic fixtures.

There is no security-support SLA or claim of an external security audit. AI code
review and passing tests are engineering checks, not security certification.
