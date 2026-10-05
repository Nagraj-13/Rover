"""
Offline checks for the dead-reckoning motion stack (no GPIO, no Flask needed).

    python test_motion.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intelligence.needle import NeedleRouter
from intelligence.tools import ToolRegistry
from motion import Calibration, MissionRunner, MotionController


class FakeDrive:
    """Records motor on/off intervals so tests can check how long each move really ran."""

    def __init__(self):
        self.log = []          # (command, speed, seconds_on)
        self._cmd = None
        self._t0 = 0.0
        self.heartbeats = 0

    def drive(self, command, speed):
        self._cmd, self._t0 = (command, speed), time.monotonic()
        return True

    def stop(self):
        if self._cmd:
            self.log.append((*self._cmd, time.monotonic() - self._t0))
            self._cmd = None

    def beat(self):
        self.heartbeats += 1


def make_stack(**cal_overrides):
    cal = Calibration(path=os.path.join(tempfile.mkdtemp(), "cal.json"))
    # Fast fake rover so the tests finish quickly: 100 cm/s and 360 deg/s at full throttle.
    cal.update({"cm_per_s_full": 100.0, "deg_per_s_full": 360.0, "deadband": 0.2,
                "drive_speed": 0.6, "turn_speed": 0.6, "settle_s": 0.01, **cal_overrides})
    fake = FakeDrive()
    motion = MotionController(fake.drive, fake.stop, fake.beat, cal)
    registry = ToolRegistry()

    def planned(cmd):
        def handler(speed=None, duration_seconds=None, distance_cm=None, degrees=None):
            return motion.submit(cmd, speed, duration_seconds, distance_cm, degrees).to_dict()
        return handler

    registry.register_tool("move_forward", planned("forward"))
    registry.register_tool("move_backward", planned("backward"))
    registry.register_tool("turn_left", planned("left"))
    registry.register_tool("turn_right", planned("right"))
    registry.register_tool("stop_rover", lambda: motion.cancel_all())
    return cal, fake, motion, registry


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        check.failed += 1


check.failed = 0


def test_parser():
    n = NeedleRouter(use_cactus=False)
    seq = n.parse_sequence("go straight for 100cm and turn left")
    check("sequence: 100cm then left", [c["name"] for c in seq] == ["move_forward", "turn_left"], str(seq))
    check("100cm not read as 100 seconds", seq[0]["arguments"] == {"distance_cm": 100.0}, str(seq[0]["arguments"]))
    check("turn defaults to 90", seq[1]["arguments"] == {"degrees": 90.0}, str(seq[1]["arguments"]))

    seq = n.parse_sequence("drive forward 1.5 meters, turn right 45 degrees, then reverse 20 cm")
    check("meters -> cm", seq[0]["arguments"]["distance_cm"] == 150.0)
    check("45 degrees", seq[1]["arguments"]["degrees"] == 45.0)
    check("reverse 20cm", seq[2]["name"] == "move_backward" and seq[2]["arguments"]["distance_cm"] == 20.0)

    seq = n.parse_sequence("move forward 2 seconds")
    check("time based still works", seq[0]["arguments"] == {"duration_seconds": 2.0}, str(seq))

    seq = n.parse_sequence("go forward 50 cm at 70% speed")
    check("explicit speed", seq[0]["arguments"].get("speed") == 0.7, str(seq))

    seq = n.parse_sequence("turn around")
    check("turn around = 180", seq[0]["arguments"]["degrees"] == 180.0, str(seq))

    check("gibberish rejected", n.parse_sequence("make me a sandwich") is None)
    check("partly understood rejected", n.parse_sequence("forward 10 cm then dance") is None)

    res = n.dispatch("go straight for 100cm and turn left", execute=False)
    check("dispatch stays on the edge", res.action == "execute_tool" and res.tier == "needle_edge", res.action)
    res = n.dispatch("patrol the perimeter", execute=False)
    check("patrol still escalates", res.action == "escalate_to_groq", res.action)
    res = n.dispatch("abort mission", execute=False)
    check("'abort mission' is a stop, not a new mission", res.tool_called == "stop_rover", str(res.tool_called))


def test_timing():
    cal, fake, motion, registry = make_stack()
    # speed 0.6 -> effective (0.6-0.2)/0.8 = 0.5 -> 50 cm/s, 180 deg/s
    job = motion.submit("forward", distance_cm=25)
    check("25 cm @50cm/s plans 0.5s", abs(job.duration_s - 0.5) < 1e-6, f"{job.duration_s:.3f}")
    job2 = motion.submit("left", degrees=90)
    check("90deg @180deg/s plans 0.5s", abs(job2.duration_s - 0.5) < 1e-6, f"{job2.duration_s:.3f}")
    job2.done.wait(3)
    cmds = [(c, round(t, 1)) for c, _s, t in fake.log]
    check("ran in order, right durations", cmds == [("forward", 0.5), ("left", 0.5)], str(cmds))
    check("watchdog heartbeat kept alive", fake.heartbeats >= 10, str(fake.heartbeats))

    # deadband clamp: asking for 10% must not produce an infinite/zero-velocity plan
    job = motion.submit("forward", distance_cm=10, speed=0.1)
    check("speed below deadband is clamped up", job.speed >= 0.25 and job.duration_s < 5, f"{job.speed} {job.duration_s:.2f}")
    job.done.wait(5)

    try:
        motion.submit("forward", distance_cm=1_000_000)
        check("absurd distance refused", False)
    except ValueError:
        check("absurd distance refused", True)


def test_cancel():
    cal, fake, motion, registry = make_stack()
    long_job = motion.submit("forward", duration_s=5)
    queued = motion.submit("left", degrees=90)
    time.sleep(0.2)
    t0 = time.monotonic()
    motion.cancel_all()
    check("cancel returns fast", time.monotonic() - t0 < 1.0)
    check("running job cancelled", long_job.status == "cancelled", long_job.status)
    check("queued job cancelled", queued.status == "cancelled", queued.status)
    check("motors off after cancel", fake._cmd is None)


def test_mission():
    cal, fake, motion, registry = make_stack()
    runner = MissionRunner(registry, motion)
    mission = {"title": "t", "steps": [
        {"step_number": 1, "title": "fwd", "tool_name": "move_forward", "parameters": {"distance_cm": 25}},
        {"step_number": 2, "title": "left", "tool_name": "turn_left", "parameters": {"degrees": 90}},
        {"step_number": 3, "title": "stop", "tool_name": "stop_rover", "parameters": {}},
    ]}
    ok, _ = runner.start(mission)
    check("mission starts", ok)
    ok2, _ = runner.start(mission)
    check("second mission refused while running", not ok2)
    deadline = time.monotonic() + 5
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    st = runner.status()
    check("mission completes", st["state"] == "completed", st["state"])
    check("all steps done", [s["status"] for s in st["steps"]] == ["done"] * 3, str([s["status"] for s in st["steps"]]))
    check("steps ran sequentially", [c for c, _s, _t in fake.log] == ["forward", "left"], str(fake.log))

    # abort mid-mission
    mission["steps"][0]["parameters"] = {"distance_cm": 500}
    runner.start(mission)
    time.sleep(0.3)
    runner.abort()
    deadline = time.monotonic() + 3
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    check("abort ends mission", runner.status()["state"] == "aborted", runner.status()["state"])
    check("motors off after abort", fake._cmd is None)

    # failing step with ABORT policy
    bad = {"title": "bad", "steps": [{"step_number": 1, "title": "x", "tool_name": "fly", "parameters": {}}]}
    runner.start(bad)
    time.sleep(0.3)
    check("unknown tool fails mission", runner.status()["state"] == "failed", runner.status()["state"])


def test_calibration():
    cal = Calibration(path=os.path.join(tempfile.mkdtemp(), "cal.json"))
    before = cal.get()["cm_per_s_full"]
    cal.adjust("linear", commanded=100, measured=80)
    check("adjust scales speed by measured/commanded", abs(cal.get()["cm_per_s_full"] - before * 0.8) < 1e-6)
    cal2 = Calibration(path=cal.path)
    check("calibration persists", abs(cal2.get()["cm_per_s_full"] - before * 0.8) < 1e-6)


if __name__ == "__main__":
    for fn in (test_parser, test_timing, test_cancel, test_mission, test_calibration):
        print(f"\n== {fn.__name__}")
        fn()
    print("\nFAILED" if check.failed else "\nALL PASSED", check.failed or "")
    sys.exit(1 if check.failed else 0)
