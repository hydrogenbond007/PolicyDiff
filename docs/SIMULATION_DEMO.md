# Recorded LIBERO demonstration

This is a purpose-built integration example, not a model benchmark. A privileged
script calibrates an action sequence for **LIBERO Spatial task 0, initial state 0**.
The same sequence is evaluated with the gripper enabled, deliberately held open,
and enabled again as an unchanged retest. There is no training or model API call.

## Recorded result

| Arm | Official outcome | Policy steps |
| --- | --- | --- |
| Scripted baseline | Success | 260 |
| Gripper deliberately disabled | No success by horizon | 1,000 |
| Unchanged baseline retest | Success | 260 |

PolicyDiff reports **1 lost case, 0 gained, 0 unresolved**, with all 3 trials
recorded and clean execution. The retest has no observed loss or gain. All captured
starting-state fingerprints match. These are three trials on one calibrated start,
not a benchmark success rate. Raw outcomes are not edited to make the demo work.

[Read the actual generated report](demo/report.md), [manifest](demo/manifest.input.json)
and [episode CSV](demo/episodes.input.csv). The comparison bundle is copied
byte-for-byte from this run: `policydiff verify --bundle docs/demo` checks it.
It omits the raw trial directories referenced by the report; reproduce the demo
to obtain those. Videos and their hash receipt are separate from the bundle.

## Reproduce

Use a trusted LIBERO checkout and a compatible Linux environment: robosuite 1.4.1,
MuJoCo, NumPy, PyTorch, Pillow, imageio and imageio-ffmpeg. The recorded run used
the existing local runtime; nothing downloads automatically. Rendering uses EGL
and works with a compatible software-rendering implementation—no rental required.
The analysis-only quickstart does not require these dependencies.

Recorded runtime: Python 3.10, NumPy 1.23.5, PyTorch 2.3.1+cu121 (CPU execution),
robosuite 1.4.1 and MuJoCo 3.2.0; LIBERO checkout commit
`8f1084e3132a39270c3a13ebe37270a43ece2a01`. The offline catalogue has its own
source pin; the execution plan records hashes of the actual local runtime assets.
Exact outcomes on other runtime versions are not promised.

From the repository root, with that environment's Python activated:

```sh
export PYTHONPATH=src
python scripts/record_sim_demo.py --stage prepare \
  --libero-root /path/to/LIBERO --output /tmp/policydiff-libero-demo
python -m policydiff evaluate \
  --config /tmp/policydiff-libero-demo/evaluation-config.json \
  --output /tmp/policydiff-libero-demo/evaluation --allow-local-code
python scripts/record_sim_demo.py --stage record \
  --libero-root /path/to/LIBERO --output /tmp/policydiff-libero-demo
python -m policydiff triage \
  --manifest /tmp/policydiff-libero-demo/evaluation/comparison/manifest.input.json \
  --episodes /tmp/policydiff-libero-demo/evaluation/comparison/episodes.input.csv \
  --format markdown
python scripts/make_demo_preview.py --run /tmp/policydiff-libero-demo \
  --output /tmp/policydiff-libero-demo/preview.gif
```

Choose a new output directory; do not overwrite an existing demonstration. On the
shared development host, wrap each simulator command with the shared CPU-slot tool.

## What runs

1. `prepare` uses simulator object geometry to construct the scripted sequence.
   The task and start are deliberately known, not held out. The adapter ignores
   images; this example says nothing about visual intelligence.
2. `evaluate` uses the ordinary PolicyDiff worker and supervisor, not a substitute
   demo engine. Three fresh processes run baseline, candidate and retest, with
   matched captured starts, seed schedule, 10 settling steps, 1,000 policy-step
   horizon and 300-second per-worker operational cap.
3. `record` replays all three action logs, checks every official success flag and
   checks the captured initial-state/observation fingerprints, and records camera
   frames. The vertical image flip is presentation-only. Full MP4s represent
   20 control steps/second. The GIF samples every 20 steps at 5 frames/second:
   **5× control-time playback**, holding each ended arm's last frame for comparison.
   Neither format represents measured inference throughput.

The candidate change is an intentionally injected **system fault**, not a weight
update. The checkpoint is a JSON action sequence, not a learned neural network.
Exposure labels mean the script was calibrated to this exact task/start; they are
not claims about a pretrained model's data. No statistical retention inference is
enabled for this fixed-case example.

## Evidence and limits

Keep `evaluation/plan.json`, `evaluation/evaluation.json`, trial action/receipt
files, the `comparison/` bundle and `replay/recordings.json` together. The bundle verifier
does not cover external videos. Recorded-video hashes are separate.

Success is LIBERO's official first-success predicate. It does not establish release,
rest, sustained contact or hardware safety. One calibrated start cannot establish
generalization, stochastic reliability or detection of naturally occurring model
regressions. The deliberately broken candidate is a demonstration control.
