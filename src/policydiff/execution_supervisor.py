"""Linux worker lifecycle and receipt collection; no planning or report generation."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from .execution_records import atomic_write, collect_receipts
from .io import encode
from .schema import EvidenceError, require

MAX_PROCESS_SCAN = 65536


def _require_supervision():
    require(sys.platform.startswith('linux') and all(hasattr(os, name) for name in
            ('waitid', 'P_PID', 'WEXITED', 'WNOWAIT', 'WNOHANG')),
            'experimental evaluation requires Linux waitid/WNOWAIT process supervision')
    require(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL,
            'evaluation requires default SIGCHLD handling and exclusive ownership of worker reaping')
    require(signal.getsignal(signal.SIGTERM) is not None,
            'evaluation requires a restorable Python SIGTERM handler')
    try:
        with os.scandir('/proc') as entries:
            next(entries, None)
        (Path('/proc') / str(os.getpid()) / 'stat').read_text()
    except OSError as exc:
        raise EvidenceError('evaluation requires a readable Linux /proc process inventory') from exc


def _live_group_members(pgid):
    """Detect a live helper while the unreaped leader still pins the group ID."""
    with os.scandir('/proc') as entries:
        for count, entry in enumerate(entries):
            if count >= MAX_PROCESS_SCAN:
                raise OSError('process inventory exceeds preview scan limit')
            if not entry.name.isdigit() or int(entry.name) == pgid:
                continue
            try:
                with (Path(entry.path) / 'stat').open() as handle:
                    data = handle.read(8193)
            except FileNotFoundError:
                continue  # Other processes may exit during this snapshot.
            parts = data.rsplit(')', 1)[-1].split()
            if len(data) > 8192 or len(parts) < 3 or not parts[2].isdigit():
                raise OSError('invalid Linux process inventory record')
            if int(parts[2]) == pgid and parts[0] not in ('Z', 'X'):
                return True
    return False


@contextmanager
def _worker_signals():
    """CLI SIGTERM uses the same owned-worker cleanup path as Ctrl-C."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    require(previous is not None, 'evaluation requires a restorable Python SIGTERM handler')

    def stop(signum, frame):
        raise KeyboardInterrupt('SIGTERM')

    signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _trial(plan_path, index, output, seconds, expected_reset=None, *, plan_sha256, max_steps):
    """Bound an owned worker group; preserve logs and partial actions on failure."""
    _require_supervision()
    output.mkdir(exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    env['PYTHONPYCACHEPREFIX'] = str(output / 'python-cache')
    trial_id = uuid.uuid4().hex
    atomic_write(output / 'admission.json', encode({'index': index, 'plan_sha256': plan_sha256,
                 'trial_id': trial_id, 'expected_reset': expected_reset, 'status': 'admitted_not_proof_of_worker_start'}))
    started = time.monotonic()
    limited, cancelled, residual_group = False, False, False
    proc, supervision_error, faults = None, None, []
    with (output / 'worker.log').open('xb') as log, _worker_signals():
        try:
            proc = subprocess.Popen([sys.executable, '-m', 'policydiff._libero_worker', str(plan_path),
                                     str(index), str(output), json.dumps(expected_reset), plan_sha256, trial_id],
                                    cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is None:
                if time.monotonic() - started > seconds or os.fstat(log.fileno()).st_size > 1024 * 1024:
                    limited = True
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            cancelled = True
        except OSError as exc:
            supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
            faults.append('worker_supervision_failed')
        finally:
            # Do not poll/reap the leader before signalling. Its live/zombie PID
            # pins the PGID; after reaping that number could belong to another run.
            if proc is not None:
                try:
                    exited = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                except OSError as exc:
                    faults.append('worker_ownership_lost')
                    supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
                else:
                    try:
                        if exited is not None:
                            try:
                                residual_group = _live_group_members(proc.pid)
                            except OSError as exc:
                                faults.append('group_inventory_failed')
                                supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        faults.append('worker_group_cleanup_failed')
                        supervision_error = f'{type(exc).__name__}: {exc}'[:1000]
                        try:
                            # The leader is still unreaped and owned here. This
                            # fallback cannot establish that helpers were stopped.
                            os.kill(proc.pid, signal.SIGKILL)
                        except OSError as fallback:
                            faults.append('worker_leader_cleanup_failed')
                            supervision_error = f'{type(fallback).__name__}: {fallback}'[:1000]
                finally:
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        faults.append('worker_reap_timeout')
        log_bytes = os.fstat(log.fileno()).st_size
    # A fast-exiting worker can cross a cap between polls. Caps are operational,
    # not a reason to erase its already recorded physical endpoint.
    limited = limited or log_bytes > 1024 * 1024 or time.monotonic() - started > seconds
    result = collect_receipts(output, plan_sha256, index, max_steps, trial_id)
    if result is None:
        result = {'status': 'interrupted' if limited or cancelled else 'infrastructure_error', 'success': None,
                  'reason': ('supervisor_cancelled' if cancelled else
                             'worker_runtime_or_log_limit' if limited else 'worker_exit_without_result')}
    if proc is not None and proc.returncode not in (None, 0):
        faults.append('worker_nonzero_exit')
    if residual_group:
        faults.append('owned_worker_group_terminated')
    if cancelled:
        faults.append('supervisor_cancelled_worker')
    if limited:
        faults.append('worker_runtime_or_log_limit')
    if faults:
        # Keep any specific receipt/worker diagnostic; supervisor faults have a
        # separate bounded vocabulary and cannot overwrite those earlier facts.
        result.setdefault('cleanup_error', '; '.join(faults))
    result['supervisor'] = {'worker_pid': proc.pid if proc is not None else None,
                            'worker_exit_code': proc.returncode if proc is not None else None,
                            'log_bytes': log_bytes, 'limit_exceeded': limited, 'cancelled': cancelled,
                            'faults': faults, 'error': supervision_error}
    return result
