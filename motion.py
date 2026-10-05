#!/usr/bin/env python3
"""
Open-loop (dead-reckoning) motion planning for the rover.

With no distance sensor, encoders, IMU or camera servo, the only way to
"go 100 cm" or "turn 90 degrees" is to convert the request into motor-on time
using a measured speed / turn rate. This module owns that conversion plus:

  * Calibration     - cm/s and deg/s at full throttle, wheel deadband, persisted to calibration.json
  * MotionController- one worker thread running queued, cancellable timed moves in order
  * MissionRunner   - executes a compiled mission's steps one by one and reports progress

The numbers in DEFAULT_CAL are guesses. Calibrate on your own floor with
POST /rover/api/calibration/adjust (see README / API docs in app.py).
"""

import json
import logging
import os
import queue
import threading
import time
import uuid

logger = logging.getLogger("RoverMotion")

CAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")

MAX_JOB_SECONDS = 120.0
MIN_JOB_SECONDS = 0.05

DEFAULT_CAL = {
    "cm_per_s_full": 60.0,    # straight-line speed at effective throttle 1.0
    "deg_per_s_full": 220.0,  # in-place pivot rate at effective throttle 1.0
    "deadband": 0.20,         # throttle below which the wheels do not turn at all
    "drive_speed": 0.50,      # throttle used when a move does not specify one
    "turn_speed": 0.50,       # skid-steer pivots need more torque than straight driving
    "settle_s": 0.30,         # pause after each move so momentum dies before the next one
}


class Calibration:
    def __init__(self, path=CAL_PATH):
        self.path = path
        self._lock = threading.Lock()
        self.values = dict(DEFAULT_CAL)
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key in DEFAULT_CAL:
                if key in saved and isinstance(saved[key], (int, float)):
                    self.values[key] = float(saved[key])
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("Could not read %s (%s). Using defaults.", self.path, e)

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.values, f, indent=2)
        except Exception as e:
            logger.warning("Could not save calibration: %s", e)

    def get(self):
        with self._lock:
            return dict(self.values)

    def update(self, changes):
        with self._lock:
            for key, val in changes.items():
                if key in DEFAULT_CAL:
                    val = float(val)
                    if val <= 0:
                        raise ValueError(f"{key} must be > 0")
                    self.values[key] = val
            self._save()
            return dict(self.values)

    def adjust(self, axis, commanded, measured):
        """Scale the speed constant by measured/commanded (e.g. asked 100 cm, got 80 -> x0.8)."""
        commanded = float(commanded)
        measured = float(measured)
        if commanded <= 0 or measured <= 0:
            raise ValueError("commanded and measured must be > 0")
        factor = max(0.2, min(5.0, measured / commanded))
        key = {"linear": "cm_per_s_full", "turn": "deg_per_s_full"}.get(axis)
        if key is None:
            raise ValueError("axis must be 'linear' or 'turn'")
        with self._lock:
            self.values[key] *= factor
            self._save()
            return dict(self.values)

    # --- conversions -------------------------------------------------------

    def min_speed(self):
        return min(1.0, self.values["deadband"] + 0.05)

    def clamp_speed(self, speed):
        return max(self.min_speed(), min(1.0, float(speed)))

    def effective(self, speed):
        db = self.values["deadband"]
        return max(0.0, (speed - db) / (1.0 - db))

    def drive_time(self, distance_cm, speed):
        return float(distance_cm) / (self.values["cm_per_s_full"] * self.effective(speed))

    def turn_time(self, degrees, speed):
        return float(degrees) / (self.values["deg_per_s_full"] * self.effective(speed))


class MotionJob:
    def __init__(self, command, speed, duration_s, distance_cm=None, degrees=None):
        self.id = uuid.uuid4().hex[:10]
        self.command = command
        self.speed = speed
        self.duration_s = duration_s
        self.distance_cm = distance_cm
        self.degrees = degrees
        self.status = "queued"  # queued | running | done | cancelled | failed
        self.error = None
        self.cancelled = threading.Event()
        self.done = threading.Event()

    def to_dict(self):
        return {
            "job_id": self.id,
            "command": self.command,
            "speed": round(self.speed, 2),
            "duration_s": round(self.duration_s, 2),
            "distance_cm": self.distance_cm,
            "degrees": self.degrees,
            "status": self.status,
            "error": self.error,
        }


class MotionController:
    """
    drive_fn(command, speed) -> bool   start the motors (False = refused)
    stop_fn()                          stop the motors
    heartbeat_fn()                     keep the safety watchdog fed while a move runs
    """

    def __init__(self, drive_fn, stop_fn, heartbeat_fn, calibration=None):
        self.cal = calibration or Calibration()
        self._drive = drive_fn
        self._stop = stop_fn
        self._heartbeat = heartbeat_fn
        self._queue = queue.Queue()
        self._jobs = {}
        self._current = None
        self._lock = threading.Lock()
        threading.Thread(target=self._worker, name="MotionWorker", daemon=True).start()

    # --- planning ----------------------------------------------------------

    def submit(self, command, speed=None, duration_s=None, distance_cm=None, degrees=None):
        """Queue a move. distance_cm / degrees take precedence over duration_s."""
        cal = self.cal
        linear = command in ("forward", "backward")
        if not linear and command not in ("left", "right"):
            raise ValueError(f"Unsupported motion command '{command}'")

        if speed is None:
            speed = cal.get()["drive_speed" if linear else "turn_speed"]
        speed = cal.clamp_speed(speed)

        if linear:
            if distance_cm is not None:
                distance_cm = float(distance_cm)
                if distance_cm <= 0:
                    raise ValueError("distance_cm must be > 0")
                duration = cal.drive_time(distance_cm, speed)
            else:
                duration = float(duration_s) if duration_s else 1.0
                degrees = None
        else:
            if degrees is not None:
                degrees = float(degrees)
                if degrees <= 0:
                    raise ValueError("degrees must be > 0")
                duration = cal.turn_time(degrees, speed)
            elif duration_s:
                duration = float(duration_s)
            else:
                degrees = 90.0
                duration = cal.turn_time(degrees, speed)
            distance_cm = None

        if duration > MAX_JOB_SECONDS:
            raise ValueError(f"Move would take {duration:.0f}s (limit {MAX_JOB_SECONDS:.0f}s)")
        duration = max(MIN_JOB_SECONDS, duration)

        job = MotionJob(command, speed, duration, distance_cm, degrees)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > 200:
                for jid in [j for j, v in self._jobs.items() if v.done.is_set()][:100]:
                    self._jobs.pop(jid, None)
        self._queue.put(job)
        return job

    def get_job(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def status(self):
        cur = self._current
        return {
            "busy": cur is not None or not self._queue.empty(),
            "queued": self._queue.qsize(),
            "current": cur.to_dict() if cur else None,
        }

    # --- cancellation ------------------------------------------------------

    def cancel_all(self):
        """Drop every queued move, abort the running one and stop the motors."""
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            job.cancelled.set()
            job.status = "cancelled"
            job.done.set()

        cur = self._current
        if cur is not None:
            cur.cancelled.set()
            cur.done.wait(0.5)
        self._stop()

    # --- worker ------------------------------------------------------------

    def _worker(self):
        while True:
            job = self._queue.get()
            if job.cancelled.is_set():
                job.status = "cancelled"
                job.done.set()
                continue
            self._current = job
            try:
                self._run(job)
            except Exception as e:
                logger.exception("Motion job crashed")
                job.status = "failed"
                job.error = str(e)
                self._stop()
            finally:
                self._current = None
                job.done.set()

    def _run(self, job):
        job.status = "running"
        if not self._drive(job.command, job.speed):
            job.status = "failed"
            job.error = "Drive command refused"
            return

        end = time.monotonic() + job.duration_s
        while not job.cancelled.is_set():
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))
            if not job.cancelled.is_set():
                self._heartbeat()

        if job.cancelled.is_set():
            # cancel_all() stops the motors itself; stopping here could kill a newer manual command.
            job.status = "cancelled"
            return

        self._stop()
        job.status = "done"
        job.cancelled.wait(self.cal.get()["settle_s"])


class MissionRunner:
    """Runs a compiled mission's steps sequentially on a background thread."""

    def __init__(self, registry, motion):
        self.registry = registry
        self.motion = motion
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._thread = None
        self._state = {"state": "idle", "steps": []}

    def is_running(self):
        with self._lock:
            return self._state.get("state") == "running"

    def status(self):
        with self._lock:
            return json.loads(json.dumps(self._state))

    def start(self, mission):
        steps = mission.get("steps") or []
        if not steps:
            return False, "Mission has no steps"
        with self._lock:
            if self._state.get("state") == "running":
                return False, "A mission is already running"
            self._abort.clear()
            self._state = {
                "state": "running",
                "mission_id": mission.get("mission_id"),
                "title": mission.get("title", "Mission"),
                "current_step": 0,
                "started_at": time.time(),
                "finished_at": None,
                "error": None,
                "steps": [
                    {
                        "step_number": s.get("step_number", i + 1),
                        "title": s.get("title", ""),
                        "tool_name": s.get("tool_name", ""),
                        "status": "pending",
                        "message": "",
                    }
                    for i, s in enumerate(steps)
                ],
            }
        self._thread = threading.Thread(target=self._run, args=(steps,), name="MissionRunner", daemon=True)
        self._thread.start()
        return True, "Mission started"

    def abort(self, reason="Aborted"):
        if not self.is_running():
            return False
        self._abort.set()
        self.motion.cancel_all()
        return True

    # --- internals ---------------------------------------------------------

    def _set_step(self, idx, status, message=""):
        with self._lock:
            self._state["steps"][idx]["status"] = status
            self._state["steps"][idx]["message"] = message
            self._state["current_step"] = idx + 1

    def _finish(self, state, error=None):
        with self._lock:
            self._state["state"] = state
            self._state["error"] = error
            self._state["finished_at"] = time.time()

    def _run(self, steps):
        try:
            for idx, step in enumerate(steps):
                if self._abort.is_set():
                    break
                ok, msg = self._run_step(idx, step)
                if self._abort.is_set():
                    break
                if not ok:
                    policy = str(step.get("on_failure", "ABORT")).upper()
                    if policy == "RETRY":
                        ok, msg = self._run_step(idx, step)
                    if not ok and policy != "SKIP":
                        self._set_step(idx, "failed", msg)
                        self.motion.cancel_all()
                        self._finish("failed", f"Step {idx + 1} failed: {msg}")
                        return
                    if not ok:
                        self._set_step(idx, "skipped", msg)
                        continue
                self._set_step(idx, "done", msg)

            if self._abort.is_set():
                with self._lock:
                    for s in self._state["steps"]:
                        if s["status"] in ("pending", "running"):
                            s["status"] = "aborted"
                self._finish("aborted", "Aborted by operator")
            else:
                self._finish("completed")
        except Exception as e:
            logger.exception("Mission runner crashed")
            self.motion.cancel_all()
            self._finish("failed", str(e))

    def _run_step(self, idx, step):
        tool = step.get("tool_name", "")
        params = dict(step.get("parameters") or {})
        self._set_step(idx, "running")

        if tool == "stop_rover":
            self.motion.cancel_all()
            return True, "Motors stopped"

        result = self.registry.execute(tool, params)
        if not result.success:
            return False, result.error or "Tool failed"

        output = result.output if isinstance(result.output, dict) else {}
        job_id = output.get("job_id")
        if not job_id:
            return True, str(output.get("message", ""))[:120]

        job = self.motion.get_job(job_id)
        if job is None:
            return False, "Motion job vanished"
        limit = time.monotonic() + job.duration_s + 15.0
        while not job.done.wait(0.1):
            if self._abort.is_set():
                return False, "Aborted"
            if time.monotonic() > limit:
                self.motion.cancel_all()
                return False, "Motion timed out"
        if job.status != "done":
            return False, job.error or f"Motion {job.status}"
        detail = f"{job.distance_cm:g} cm" if job.distance_cm else (f"{job.degrees:g}°" if job.degrees else f"{job.duration_s:.1f}s")
        return True, f"{tool} {detail} in {job.duration_s:.1f}s"
