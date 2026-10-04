"""
EdgeRover — Multi-Tier Intelligence Demonstration Script (Laptop Edition).

Demonstrates the 4-Tier Hybrid Intelligence Stack running locally on this laptop:
- Tier 1: Groq Strategic Brain (gpt-oss-120b / gpt-oss-20b / qwen3.8-27b / Local Engine)
- Tier 2: Needle 3 Edge Tool Calling (Cactus Compute / Embedded SLM Router)
- Tier 3: Laya System-1 Decision Evaluator (Typed Choice, Score, Noul Decisions)

Usage:
    python sample_intelligence_demo.py
    # or with Groq API key:
    $env:GROQ_API_KEY="gsk_..." ; python sample_intelligence_demo.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List

# Ensure current directory is in sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from intelligence.groq_client import GroqBrain, groq_brain
from intelligence.laya import (
    AvoidanceDirection,
    EventSeverity,
    LayaDecisionEngine,
    RecommendedAction,
    WorldState,
    laya_engine,
)
from intelligence.needle import NeedleRouter, needle_router
from intelligence.tools import ToolRegistry, tool_registry



# ANSI color codes for terminal display
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner(title: str, subtitle: str = "") -> None:
    print()
    print(f"{CYAN}{BOLD}{'=' * 72}{RESET}")
    print(f"{CYAN}{BOLD}  {title.center(68)}{RESET}")
    if subtitle:
        print(f"{DIM}  {subtitle.center(68)}{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 72}{RESET}")
    print()


def demo_needle_edge_tool_calling() -> None:
    """Demonstrates Needle 2 local natural language command translation to tool calls."""
    print_banner(
        "TIER 2: NEEDLE 2 — EDGE TOOL CALLING DEMO",
        "Target Envelope: Sub-50ms Local Execution | Zero Cloud Dependency"
    )

    test_commands = [
        "Move forward 2.5 seconds at 50% speed",
        "Turn right 90 degrees",
        "Snap a photo of the perimeter gate",
        "Stop rover immediately",
        "What is the battery level and distance?",
        "Send telegram alert intrusion detected at north fence",
        "Patrol warehouse perimeter for 15 minutes, alert if person seen, and return to dock", # Complex!
    ]

    print(f"{DIM}Simulating real-time natural language commands from dashboard or voice input:{RESET}\n")

    for idx, cmd in enumerate(test_commands, 1):
        print(f"{BOLD}[Command {idx}]{RESET} {YELLOW}\"{cmd}\"{RESET}")
        res = needle_router.dispatch(cmd, execute=True)

        if res.action == "execute_tool":
            print(f"  ├── {GREEN}Action:{RESET} Dispatched Tool Call")
            print(f"  ├── {CYAN}Tool:{RESET} {BOLD}{res.tool_called}(){RESET}")
            print(f"  ├── {CYAN}Parameters:{RESET} {json.dumps(res.parameters)}")
            print(f"  ├── {CYAN}Engine:{RESET} {res.engine} (Confidence: {res.confidence:.0%})")
            print(f"  └── {MAGENTA}Latency:{RESET} {BOLD}{res.latency_ms:.2f} ms{RESET}")
        elif res.action == "escalate_to_groq":
            print(f"  ├── {YELLOW}Action:{RESET} {BOLD}Escalated to Tier 1 Groq Cloud Brain{RESET}")
            print(f"  ├── {CYAN}Reason:{RESET} Complex multi-step / long-term strategic mission identified")
            print(f"  └── {MAGENTA}Latency:{RESET} {BOLD}{res.latency_ms:.2f} ms{RESET}")
        print()

    print(f"{GREEN}✔ Needle 2 average edge dispatch latency:{RESET} {BOLD}{needle_router.get_average_latency_ms():.2f} ms{RESET}")


def demo_laya_decision_evaluator() -> None:
    """Demonstrates Laya System-1 typed decisions over diverse World States."""
    print_banner(
        "TIER 3: LAYA — SYSTEM-1 TYPED DECISION ENGINE",
        "Target Envelope: Sub-15ms Non-Autoregressive Typed Triage & Avoidance"
    )

    scenarios = [
        (
            "Scenario A: Nominal Cruising (Clear Path)",
            WorldState(
                distance_cm=145.0,
                detections=[],
                battery_pct=88.0,
                current_speed=0.35,
                rover_state="PATROL",
            ),
        ),
        (
            "Scenario B: Caution Zone (Obstacle Offset Left)",
            WorldState(
                distance_cm=48.0,
                detections=[{"label": "chair", "confidence": 0.82, "offset_x": -0.35}],
                battery_pct=84.0,
                current_speed=0.35,
                rover_state="PATROL",
            ),
        ),
        (
            "Scenario C: Critical Security Breach (Intruder Approaching)",
            WorldState(
                distance_cm=26.0,
                detections=[{"label": "person", "confidence": 0.95, "offset_x": 0.05}],
                battery_pct=81.0,
                current_speed=0.30,
                rover_state="PATROL",
            ),
        ),
    ]

    for title, state in scenarios:
        print(f"{BOLD}{title}{RESET}")
        print(f"  State: {DIM}{state.to_state_text()}{RESET}")

        # Triage evaluation
        triage = laya_engine.evaluate_triage(state)
        # Avoidance evaluation
        nav = laya_engine.evaluate_navigation(state)

        sev_color = GREEN if triage.severity == EventSeverity.INFO else (YELLOW if triage.severity == EventSeverity.WARNING else RED)

        print(f"  ├── {CYAN}Laya Typed Answers:{RESET}")
        print(f"  │    • Severity: {sev_color}{BOLD}{triage.severity.value}{RESET}")
        print(f"  │    • Action:   {BOLD}{triage.action.value}{RESET}")
        print(f"  │    • Urgency:  {triage.laya_answers.get('urgency', {}).get('label', 'low')}")
        print(f"  │    • Collision Risk (noul): {triage.laya_answers.get('collision_risk', {}).get('noul', 0.0):.1%}")
        print(f"  ├── {CYAN}Navigation Decision:{RESET} {BOLD}{nav.direction.value}{RESET} (Turn: {nav.steer_angle_deg}°, Throttle: {nav.target_speed*100:.0f}%)")
        print(f"  ├── {CYAN}Rationale:{RESET} {triage.rationale}")
        print(f"  └── {MAGENTA}Latency:{RESET} {BOLD}{triage.latency_ms:.3f} ms{RESET} (Engine: {triage.engine})")
        print()

    metrics = laya_engine.get_metrics()
    print(f"{GREEN}✔ Laya average System-1 decision latency:{RESET} {BOLD}{metrics['average_latency_ms']:.3f} ms{RESET}")


def demo_groq_strategic_brain() -> None:
    """Demonstrates Groq Tier 1 strategic mission compilation and debrief generation."""
    print_banner(
        "TIER 1: GROQ — STRATEGIC CLOUD BRAIN DEMO",
        "Target Envelope: ~300-600ms High-Level Planning & Debrief Synthesis"
    )

    cloud_status = f"{GREEN}ONLINE (LPU Key Configured){RESET}" if groq_brain.is_cloud_ready() else f"{YELLOW}STANDALONE LOCAL COMPILER (Set GROQ_API_KEY for Cloud LPUs){RESET}"
    print(f"Groq Cloud Status: {cloud_status}")
    print(f"Active Model: {BOLD}{groq_brain.model}{RESET}\n")

    mission_prompt = "Patrol warehouse perimeter. Alert if any person detected. Return to base after 10 minutes."
    print(f"{BOLD}Compiling Mission Prompt:{RESET} {YELLOW}\"{mission_prompt}\"{RESET}\n")

    spec = groq_brain.compile_mission(mission_prompt)

    print(f"{GREEN}✔ Mission Compiled Successfully!{RESET}")
    print(f"  ├── {CYAN}Mission ID:{RESET} {spec.mission_id}")
    print(f"  ├── {CYAN}Title:{RESET} {BOLD}{spec.title}{RESET}")
    print(f"  ├── {CYAN}Source:{RESET} {spec.compiler_source}")
    print(f"  ├── {CYAN}Est. Duration:{RESET} {spec.estimated_duration_s:.0f} seconds")
    print(f"  ├── {CYAN}Safety Rules:{RESET}")
    for rule in spec.safety_rules:
        print(f"  │    • {rule}")
    print(f"  ├── {CYAN}Execution Graph ({len(spec.steps)} steps):{RESET}")
    for s in spec.steps:
        print(f"  │    {DIM}[Step {s.step_number}]{RESET} {BOLD}{s.title}{RESET} ➔ {s.tool_name}({json.dumps(s.parameters)})")
    print(f"  └── {MAGENTA}Compilation Latency:{RESET} {BOLD}{spec.compilation_latency_ms:.2f} ms{RESET}\n")

    # Debrief synthesis demonstration
    print(f"{BOLD}Synthesizing End-of-Mission Executive Debrief:{RESET}")
    simulated_events = [
        {"severity": "INFO", "reason": "Pre-flight checks passed", "detections": []},
        {"severity": "WARNING", "reason": "Circumvented obstacle on patrol path", "detections": [{"label": "chair"}]},
        {"severity": "CRITICAL", "reason": "Unauthorized person sighted at east boundary", "detections": [{"label": "person"}]},
    ]
    simulated_telemetry = {
        "duration_seconds": 645.0,
        "battery_start_pct": 89.0,
        "battery_end_pct": 71.0,
        "obstacles_avoided": 3,
    }

    debrief = groq_brain.generate_mission_debrief(spec.to_dict(), simulated_events, simulated_telemetry)

    print(f"{GREEN}✔ Executive Debrief Generated:{RESET}")
    print(f"  ├── {CYAN}Mission:{RESET} {debrief.mission_title} ({debrief.duration_formatted})")
    print(f"  ├── {CYAN}Battery:{RESET} {debrief.battery_start_pct}% ➔ {debrief.battery_end_pct}% ({debrief.battery_delta_pct}% consumed)")
    print(f"  ├── {CYAN}Obstacles Avoided:{RESET} {debrief.obstacles_avoided_count}")
    print(f"  ├── {CYAN}Critical Events:{RESET} {debrief.critical_events_count}")
    print(f"  ├── {CYAN}Summary:{RESET} {debrief.executive_summary}")
    print(f"  ├── {CYAN}Recommendations:{RESET}")
    for r in debrief.recommendations:
        print(f"  │    • {r}")
    print(f"  └── {MAGENTA}Synthesis Latency:{RESET} {BOLD}{debrief.synthesis_latency_ms:.2f} ms{RESET}\n")


def demo_end_to_end_autonomous_mission() -> None:
    """Executes a simulated end-to-end mission coordinating Groq, Needle, and Laya."""
    print_banner(
        "INTEGRATED MISSION LOOP: GROQ + NEEDLE + LAYA",
        "Full Hybrid Autonomous Execution Flow"
    )

    print("Step 1: User submits strategic mission prompt...")
    prompt = "Inspect north parking lot for 10 minutes, notify me if a person is detected, and return to base."
    print(f"Prompt: {YELLOW}\"{prompt}\"{RESET}\n")

    # 1. Needle evaluates complexity and escalates
    needle_eval = needle_router.dispatch(prompt, execute=False)
    print(f"[Needle Tier 2] Evaluated prompt in {needle_eval.latency_ms:.2f}ms ➔ {BOLD}{needle_eval.action}{RESET}")

    # 2. Groq compiles mission spec
    print("[Groq Tier 1] Compiling mission execution plan...")
    mission = groq_brain.compile_mission(prompt)
    print(f"[Groq Tier 1] Mission '{mission.title}' compiled with {len(mission.steps)} steps.\n")

    # 3. Execution loop with live Laya safety triage
    print(f"{BOLD}Executing mission steps with active Laya System-1 safety interlock:{RESET}")
    events_log = []

    for step in mission.steps:
        print(f"  ▶ Executing Step {step.step_number}: {step.title}...")

        # Needle executes atomic step tool
        exec_res = tool_registry.execute(step.tool_name, step.parameters)

        # Laya senses World State simultaneously
        # Simulate obstacle on step 3
        if step.step_number == 3:
            current_state = WorldState(
                distance_cm=42.0,
                detections=[{"label": "backpack", "offset_x": 0.25}],
                battery_pct=83.0,
                current_speed=0.35,
            )
        else:
            current_state = WorldState(
                distance_cm=130.0,
                detections=[],
                battery_pct=85.0 - (step.step_number * 1.5),
                current_speed=0.35,
            )

        triage = laya_engine.evaluate_triage(current_state)

        if triage.severity == EventSeverity.WARNING:
            nav = laya_engine.evaluate_navigation(current_state)
            print(f"    {YELLOW}⚠️  Laya Warning ({triage.latency_ms:.2f}ms): {triage.rationale}{RESET}")
            print(f"    ↪ Triggering reactive avoidance: {nav.direction.value} ({nav.steer_angle_deg}°)")
            events_log.append({"severity": "WARNING", "reason": triage.rationale, "detections": current_state.detections})
        else:
            print(f"    {GREEN}✔  Laya Nominal ({triage.latency_ms:.2f}ms): {triage.rationale}{RESET}")
            events_log.append({"severity": "INFO", "reason": "Nominal step progress", "detections": []})

        time.sleep(0.05)  # brief pause for visual progression

    print()
    # 4. Groq mission debrief
    print("[Groq Tier 1] Generating end-of-mission executive debrief...")
    summary = {
        "duration_seconds": 180.0,
        "battery_start_pct": 85.0,
        "battery_end_pct": 77.5,
        "obstacles_avoided": 1,
    }
    debrief = groq_brain.generate_mission_debrief(mission.to_dict(), events_log, summary)
    print(f"\n{CYAN}{BOLD}Executive Summary Dispatched to Security Channel:{RESET}")
    print(f"{debrief.executive_summary}\n")


def demo_performance_benchmarks() -> None:
    """Runs a 100-iteration benchmark suite measuring throughput and latency percentiles."""
    print_banner(
        "ACADEMIC LATENCY & THROUGHPUT BENCHMARK (PRD Section 14)",
        "Benchmarking Needle 2 (Edge Tool) vs Laya (System-1 Decision Engine)"
    )

    iterations = 10

    # 1. Benchmark Laya Official Engine (Neural Transformer Checkpoint)
    print(f"Benchmarking Official Laya Decision Engine over {iterations} evaluations...")
    test_state = WorldState(
        distance_cm=35.0,
        detections=[{"label": "person", "confidence": 0.90, "offset_x": -0.2}],
        battery_pct=80.0,
    )
    laya_times = []
    for i in range(iterations):
        print("Iteration :", i + 1)
        t0 = time.perf_counter()
        res1 = laya_engine.evaluate_triage(test_state)
        res2 = laya_engine.evaluate_navigation(test_state)
        print("Result : ", res1.to_dict(), res2.to_dict())
        laya_times.append((time.perf_counter() - t0) * 1000.0)

    laya_avg = sum(laya_times) / len(laya_times)
    laya_min = min(laya_times)
    laya_max = max(laya_times)
    laya_p99 = sorted(laya_times)[int(len(laya_times) * 0.99)]
    laya_ops = 1000.0 / laya_avg if laya_avg > 0 else 0

    # 2. Benchmark Embedded System-1 Reflex Engine (Sub-millisecond Edge Control)
    print(f"\nBenchmarking Embedded Reflex Engine (50Hz Real-Time Interlock) over {iterations} evaluations...")
    reflex_engine = LayaDecisionEngine(use_official_laya=False)
    reflex_times = []
    for i in range(iterations):
        t0 = time.perf_counter()
        r1 = reflex_engine.evaluate_triage(test_state)
        r2 = reflex_engine.evaluate_navigation(test_state)
        reflex_times.append((time.perf_counter() - t0) * 1000.0)

    reflex_avg = sum(reflex_times) / len(reflex_times)
    reflex_min = min(reflex_times)
    reflex_max = max(reflex_times)
    reflex_p99 = sorted(reflex_times)[int(len(reflex_times) * 0.99)]
    reflex_ops = 1000.0 / reflex_avg if reflex_avg > 0 else 0

    # 3. Benchmark Needle Edge Tool Dispatcher (Cactus Needle 3)
    print(f"\nBenchmarking Needle Edge Tool Dispatcher over {iterations} evaluations...")
    test_prompt = "Move forward 2 seconds at 40% speed"
    needle_times = []
    for i in range(iterations):
        print("Iteration : ", i + 1)
        t0 = time.perf_counter()
        res = needle_router.dispatch(test_prompt, execute=False)
        needle_times.append((time.perf_counter() - t0) * 1000.0)
        print("Result : ", res.to_dict())

    needle_avg = sum(needle_times) / len(needle_times)
    needle_min = min(needle_times)
    needle_max = max(needle_times)
    needle_p99 = sorted(needle_times)[int(len(needle_times) * 0.99)]
    needle_ops = 1000.0 / needle_avg if needle_avg > 0 else 0

    print()
    print(f"{BOLD}Benchmark Results Summary:{RESET}")
    print(f"┌{'─'*30}┬{'─'*13}┬{'─'*13}┬{'─'*13}┬{'─'*16}┐")
    print(f"│ {'Component':<28} │ {'Min Latency':<11} │ {'Avg Latency':<11} │ {'p99 Latency':<11} │ {'Throughput':<14} │")
    print(f"├{'─'*30}┼{'─'*13}┼{'─'*13}┼{'─'*13}┼{'─'*16}┤")
    print(f"│ {'Laya Official (PyTorch CPU)':<28} │ {laya_min:7.2f} ms  │ {laya_avg:7.2f} ms  │ {laya_p99:7.2f} ms  │ {laya_ops:8.1f} ops/s  │")
    print(f"│ {'Laya Reflex (Sub-ms Edge)':<28} │ {reflex_min:7.3f} ms  │ {reflex_avg:7.3f} ms  │ {reflex_p99:7.3f} ms  │ {reflex_ops:8.1f} ops/s  │")
    print(f"│ {'Needle 2 (Cactus Needle 3)':<28} │ {needle_min:7.2f} ms  │ {needle_avg:7.2f} ms  │ {needle_p99:7.2f} ms  │ {needle_ops:8.1f} ops/s  │")
    print(f"└{'─'*30}┴{'─'*13}┴{'─'*13}┴{'─'*13}┴{'─'*16}┘")
    print()


def main():
    print_banner(
        "EDGEROVER AI INTELLIGENCE STACK DEMO",
        "Demonstrating Groq (Tier 1), Needle 2 (Tier 2), and Laya (Tier 3)"
    )

    # 1. Needle
    demo_needle_edge_tool_calling()

    # 2. Laya
    demo_laya_decision_evaluator()

    # 3. Groq
    demo_groq_strategic_brain()

    # 4. Integrated loop
    demo_end_to_end_autonomous_mission()

    # 5. Benchmarks
    demo_performance_benchmarks()

    print(f"{GREEN}{BOLD}All demonstrations completed successfully!{RESET}\n")


if __name__ == "__main__":
    main()
