# Experimental task catalogue and local evaluation

`catalog` is offline metadata selection. `evaluate` is an explicit, optional
execution path around LIBERO; it is not an arbitrary-checkpoint loader or hardware
runner. The pure comparison commands remain independent of simulator dependencies.

## Select tasks

```sh
policydiff catalog
policydiff catalog --suite libero_object
policydiff catalog --query drawer
```

The catalogue contains 130 task names from the pinned LIBERO source: Spatial 10,
Object 10, Goal 10, downstream 10 and upstream 90. IDs such as `libero_object.9` use
task-order index0. Every listed task is marked `listed`, not ready/successful.
Suite membership never establishes your policy's training exposure. See
[third-party attribution](THIRD_PARTY_NOTICES.md).

## Supply one compatible local adapter

The initial ABI is `libero-panda-rgb128-proprio-osc7-v1`: Panda, OSC_POSE control,
20 Hz, two 128×128 RGB uint8 camera arrays and finite end-effector position/quaternion
and gripper-joint position arrays. Names/shapes are:

- `agentview_image`, `robot0_eye_in_hand_image`:128×128×3.
- `robot0_eef_pos`:3; `robot0_eef_quat`:4; `robot0_gripper_qpos`:2.

Images retain upstream orientation; there is no automatic flipping, normalization,
crop, resizing outside environment rendering, or action conversion. The adapter
must apply exactly what its policy was trained to consume. Object/evaluator state
is not included in this observation mapping. Language comes from the task.

The explicitly selected Python file declares `POLICYDIFF_ABI` and implements
`load_policy(checkpoint_path, options)`. It returns an object implementing
`reset(instruction=..., seed=..., max_steps=...)` and `act(observation)`.
`act` returns one numeric seven-element action in the native environment action
space: three position deltas, three rotation deltas, one gripper command.
Invalid shape, nonfinite values and out-of-range actions fail; nothing is clipped
or silently repaired. Adapter-internal exceptions are recorded separately from
invalid returned actions and do not prove a random external infrastructure fault.

Checkpoint loading, model architecture, image conventions, normalization, history,
action chunks and model RNG management belong to the adapter. One local checkpoint
file per arm is supported; sharded/directory checkpoints and remote servers are
not automatically supported. Declaring the ABI is an assertion, not a semantic
proof that a model or its preprocessing is correct.

## Configure an evaluation

Execution requires Linux with `waitid`/`WNOWAIT` and readable `/proc` process
metadata for owned-group cleanup. Activate an existing compatible LIBERO environment
(experimental runtime: robosuite 1.4.1, with NumPy, PyTorch, MuJoCo and LIBERO's
dependencies installed), and install PolicyDiff there. No dependency/model/dataset
download is automatic.
The worker uses EGL rendering and a package-local `PYTHONPATH`; install adapter
dependencies into this interpreter rather than relying on inherited `PYTHONPATH`.
OSMesa/GLX-only execution is not supported by this experimental runner.
Use default `SIGCHLD` handling and do not independently reap PolicyDiff's worker
children; the supervisor must retain their identities until group cleanup finishes.
An externally installed, non-restorable SIGTERM handler is rejected before admission.
Paths in this configuration are relative to the configuration file:

```json
{
  "evaluation_schema_version": 1,
  "title": "My policy update",
  "libero_root": "../LIBERO",
  "adapter": "my_policy.py",
  "family": "my-policy-family",
  "baseline": {"checkpoint": "before.pt", "options": {}},
  "candidate": {"checkpoint": "after.pt", "options": {}},
  "change": {"kind": "weights", "description": "Fine-tuned checkpoint", "upstream_exposure": "unknown"},
  "retest": true,
  "seed": 17,
  "timeout_seconds": 120,
  "tasks": [
    {"id": "libero_object.9", "states": [0, 1], "max_steps": 220,
     "role": "old_unrehearsed", "parent_exposure": "included", "update_exposure": "excluded"}
  ]
}
```

Replace the exposure labels with actual known training history. Do not use the
example's claims by default. Weight-only comparisons require identical adapter
options and different checkpoint bytes. Options are compared as canonical JSON:
object-key order is ignored, but Boolean/numeric types and signed zero are not
interchangeable. Context/system comparisons retain the
checkpoint identity and record changed options; mixed changes remain unsupported.

```sh
policydiff evaluate --config evaluation.json --output new-evaluation --allow-local-code
```

The trust flag is required: your adapter is executable Python, and upstream initial
state/checkpoint files can use pickle. Only run trusted local code and assets.
Fresh process groups provide lifecycle isolation and bounded worker execution,
**not a security sandbox**. User adapters can themselves perform arbitrary actions;
PolicyDiff does not enforce offline access or prevent filesystem/network access.

## Execution and evidence boundaries

The run freezes selected task/start indices, adapter/checkpoint/source/asset byte
hashes (including PolicyDiff Python source), selected runtime dependency versions,
seeds and budgets before trials. Other adapter imports and dependency bytes are
not exhaustively hashed. Complete scoped inventories include `.py` files under
the LIBERO `libero/` directory (including outer package initializers) and its
assets; additions, removals and byte changes are checked before execution and at
trial sealing. The explicit adapter runs from its checked source snapshot, not
a cached `.pyc`. Workers use a fresh private Python cache prefix. This does not
prove which arbitrary transitive/native dependencies an adapter executes. It creates
a fresh worker/environment for each baseline/candidate/retest cell, restores the
selected initial state and performs ten fixed zero-motion/open-gripper settling
steps before policy action. A success during initialization is a setup error.
The policy budget excludes settling. These are explicit harness conventions, not
a claim of exact replication of every published LIBERO evaluation protocol.

Success is the original environment predicate after each policy action, stopping
at the first success within the selected horizon. This does not certify sustained
success or physical safety. Initial physics/control/model-XML and observation
fingerprints are compared before candidate/retest policy execution; the actual
captured fields are saved, not claimed to exhaust hidden simulator/controller state.
RNG identity describes a declared seeded schedule, not a complete snapshot or
proof of deterministic inference. Outcomes that vary on retest remain visible.

Worker `steps` counts policy calls to `env.step` that returned, excluding settling.
A later grading failure or cancellation preserves that count but leaves the
outcome unknown. An `env.step` exception does not confirm a completed step and
does not prove the simulator remained unchanged. A grading or trace-write fault
can leave fewer action-trace entries than confirmed steps; retain the worker
diagnostic rather than inferring missing success labels. Elapsed rollout time is
optional and can be absent after a fault; it is not a zero-duration measurement.

The per-worker operational cap includes loading, reset, execution and cleanup;
it is not a task-success deadline. Timeouts are interruptions. Cleanup faults
cannot erase a terminal outcome already recorded. Infrastructure/cleanup faults
stop further admissions and preserve partial data; no automatic retries/resume.
Cleanup allows up to one additional second to reap the leader. Signalling/reaping
failures remain explicit faults and can leave processes alive; no later signalling
is authorized merely by a saved PID. Helpers that escape the owned group are outside
this lifecycle guarantee.
Known pairing mismatches abort without a comparison report.
Ctrl-C or SIGTERM during main-thread CLI worker supervision stops that owned group and records an interruption
or preserves its already recorded terminal outcome, then stops admissions. Abrupt
SIGKILL/parent termination, cancellation outside worker supervision, or filesystem failure
can leave only partial artifacts; these are not automatically resumed or certified.

The output retains the original configuration, frozen plan/planned manifest,
per-trial logs/actions/initial observations, supervisor outcomes, progress CSV and
a `comparison/` bundle when the recorded evidence passes input validation.
Evidence-reference text in that bundle is relative to the **evaluation root**;
the existing verifier does not open/verify those external trial artifacts.

Worker receipts are bounded to 32 KiB and bind schema version, frozen-plan hash,
cell index and unique admission ID. The worker checks admitted plan bytes before
loading the environment. Strict validation rejects malformed JSON, ambiguous
fields, wrong identities and impossible outcome/step combinations. A valid saved
terminal outcome survives a malformed or absent final record, with an explicit
execution fault. Conflicting records abort the comparison rather than selecting
one. IDs/hashes detect ordinary mixups, not a malicious adapter or forged evidence.
Supervisor fault codes and a bounded diagnostic are recorded separately under
`supervisor`, preserving any original worker/receipt `cleanup_error`.
Missing/malformed transport diagnostics use `receipt_errors` alongside the original
worker diagnostic, without truncating it. These are supervisor-side additions,
not new fields in the worker receipt schema.
`receipt_cleanup_errors` retains each valid receipt's worker diagnostic; a final
record cannot erase a terminal cleanup fault by omitting it.

The measured endpoint is checkpointed before the potentially slow seal scan;
`input_integrity: pending` is not verified evidence. The terminal checkpoint is
updated atomically after sealing. Pending or failed seals retain measured raw
outcomes but block comparison publication. Checks at two instants do not prove
inputs were immutable between them. Keep all inputs quiescent during evaluation.

Progress, worker receipts and summaries use a flushed/fsynced temporary file and
atomic replacement, retaining the previous intact file if publication fails.
This is atomic single-file visibility, not a multi-file transaction, power-loss
guarantee or automatic recovery command. Per-trial admission and outcome files
remain available when progress JSON/CSV snapshots lag or cannot be published.
An admission or `active_trial` entry is not proof that a worker actually started.

Evaluation reports use fixed-case descriptive analysis only. No IID sampling,
generalization guarantee, automated deployment gate or task competence is inferred.
The summary separates `complete` (recorded outcome coverage) from `execution_clean`
(no observed lifecycle fault), and includes `stop_reason`. Exit 0 requires both,
not a candidate pass. Exit 3 means incomplete coverage or unclean execution, even
if all outcomes were saved; input, contradictory-evidence and pairing failures use 2.
The nested comparison bundle describes outcomes/coverage, not execution health;
retain `evaluation.json` and the trial evidence with it.
Preview limits: 100 selected tasks, 300 total trials, 10000 policy steps per trial,
1–3600 seconds per worker and a 1 MiB log stop threshold. Polling permits transient
runtime/log-size overshoot; final checks still flag fast-exit overshoots. Neither
limit is a hard realtime/storage guarantee. Linux process-group supervision is
required; analysis and catalogue commands do not require it. Listing 130 tasks
does not establish execution validation across all 130.
