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

Activate an existing compatible LIBERO environment (experimental runtime:
robosuite 1.4.1, with NumPy, PyTorch, MuJoCo and LIBERO's dependencies installed),
and install PolicyDiff there. No dependency/model/dataset download is automatic.
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
options and different checkpoint bytes. Context/system comparisons retain the
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
not exhaustively hashed. It creates
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

The per-worker operational cap includes loading, reset, execution and cleanup;
it is not a task-success deadline. Timeouts are interruptions. Cleanup faults
cannot erase a terminal outcome already recorded. Infrastructure/cleanup faults
stop further admissions and preserve partial data; no automatic retries/resume.
Known pairing mismatches abort without a comparison report.
Ctrl-C while supervising a worker stops that owned group and records an interruption
or preserves its already recorded terminal outcome, then stops admissions. Abrupt
parent termination, cancellation outside worker supervision, or filesystem failure
can leave only partial artifacts; these are not automatically resumed or certified.

The output retains the original configuration, frozen plan/planned manifest,
per-trial logs/actions/initial observations, supervisor outcomes, progress CSV and
a `comparison/` bundle when the recorded evidence passes input validation.
Evidence-reference text in that bundle is relative to the **evaluation root**;
the existing verifier does not open/verify those external trial artifacts.
Progress files are best-effort checkpoints, not power-loss-safe transactions.

Evaluation reports use fixed-case descriptive analysis only. No IID sampling,
generalization guarantee, automated deployment gate or task competence is inferred.
Exit 0 means execution finished with complete recorded outcome coverage, not that
the candidate passed. Exit 3 means incomplete coverage; input/pairing failures use 2.
Preview limits: 100 selected tasks, 300 total trials, 10000 policy steps per trial,
1–3600 seconds per worker and 1 MiB worker logs. POSIX process-group supervision is
required. Listing 130 tasks does not establish execution validation across all 130.
