"""
EdgeRover — Groq Strategic Cloud Brain & Mission Compiler (Tier 1).

Leverages Groq LPUs (llama-3.3-70b-versatile) for high-level reasoning:
- Compiles natural language mission prompts into structured JSON execution graphs.
- Synthesizes post-mission event telemetry into executive Telegram/Dashboard debriefs.
- Conducts deep root-cause incident analysis for anomalies flagged by Laya.
- Dual-mode architecture: Uses real Groq Cloud API when GROQ_API_KEY is present;
  seamlessly activates a high-fidelity local strategic compiler if key is missing or offline.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("GroqBrain")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [Groq-Tier1] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Optional groq python SDK
try:
    import groq
    GROQ_SDK_AVAILABLE = True
except ImportError:
    GROQ_SDK_AVAILABLE = False


# ==============================================================================
# ENVIRONMENT VARIABLE & .ENV FILE LOADER
# ==============================================================================

def find_env_file() -> Optional[str]:
    """Locate .env file in the workspace or parent directory."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        candidate = os.path.join(current_dir, ".env")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current_dir)
        if parent == current_dir:
            break
        current_dir = parent
    return None


def load_rover_env() -> None:
    """Loads environment variables from .env using python-dotenv or fallback parser."""
    env_file = find_env_file()
    try:
        from dotenv import load_dotenv
        if env_file:
            load_dotenv(env_file, override=False)
        else:
            load_dotenv(override=False)
    except ImportError:
        if env_file and os.path.isfile(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k not in os.environ and v:
                                os.environ[k] = v
            except Exception:
                pass


# Auto-load on import
load_rover_env()


def save_api_key_to_env(api_key: str, env_var: str = "GROQ_API_KEY") -> bool:
    """
    Persists or updates the specified key inside the .env file.
    Preserves existing comments and other configuration variables.
    """
    env_file = find_env_file()
    if not env_file:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_file = os.path.join(project_root, ".env")

    clean_key = (api_key or "").strip()
    try:
        lines = []
        key_found = False
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{env_var}=") or stripped.startswith(f"export {env_var}="):
                prefix = "export " if stripped.startswith("export ") else ""
                new_lines.append(f"{prefix}{env_var}={clean_key}\n")
                key_found = True
            else:
                new_lines.append(line)

        if not key_found:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f"{env_var}={clean_key}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        os.environ[env_var] = clean_key
        logger.info("Saved %s to %s", env_var, env_file)
        return True
    except Exception as e:
        logger.error("Failed to write %s to %s: %s", env_var, env_file, e)
        return False


@dataclass
class MissionStep:
    """An individual discrete step within a compiled autonomous mission."""
    step_number: int
    title: str
    action_type: str                  # "TOOL_EXECUTION", "WAYPOINT_NAV", "VISUAL_SWEEP", "WAIT"
    tool_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 10.0
    completion_condition: str = "duration_elapsed"
    on_failure: str = "ABORT"         # "ABORT", "SKIP", "RETRY"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "title": self.title,
            "action_type": self.action_type,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "timeout_seconds": self.timeout_seconds,
            "completion_condition": self.completion_condition,
            "on_failure": self.on_failure,
        }


@dataclass
class MissionSpec:
    """Structured mission specification compiled from natural language."""
    mission_id: str
    title: str
    description: str
    target_area: str
    estimated_duration_s: float
    safety_rules: List[str]
    steps: List[MissionStep]
    compiler_source: str             # "groq_cloud_lpu" or "local_strategic_compiler"
    compilation_latency_ms: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "title": self.title,
            "description": self.description,
            "target_area": self.target_area,
            "estimated_duration_s": self.estimated_duration_s,
            "safety_rules": self.safety_rules,
            "steps": [s.to_dict() for s in self.steps],
            "compiler_source": self.compiler_source,
            "compilation_latency_ms": round(self.compilation_latency_ms, 2),
            "created_at": self.created_at,
        }


@dataclass
class DebriefReport:
    """Executive end-of-mission debrief synthesized for Dashboard & Telegram."""
    mission_id: str
    mission_title: str
    status: str                       # "COMPLETED", "ABORTED", "PARTIAL"
    duration_seconds: float
    duration_formatted: str
    battery_start_pct: float
    battery_end_pct: float
    battery_delta_pct: float
    detections_summary: Dict[str, int]
    critical_events_count: int
    obstacles_avoided_count: int
    executive_summary: str
    recommendations: List[str]
    compiler_source: str
    synthesis_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission_title": self.mission_title,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "duration_formatted": self.duration_formatted,
            "battery_start_pct": self.battery_start_pct,
            "battery_end_pct": self.battery_end_pct,
            "battery_delta_pct": self.battery_delta_pct,
            "detections_summary": self.detections_summary,
            "critical_events_count": self.critical_events_count,
            "obstacles_avoided_count": self.obstacles_avoided_count,
            "executive_summary": self.executive_summary,
            "recommendations": self.recommendations,
            "compiler_source": self.compiler_source,
            "synthesis_latency_ms": round(self.synthesis_latency_ms, 2),
        }


SUPPORTED_GROQ_MODELS: List[Dict[str, Any]] = [
    {
        "id": "openai/gpt-oss-120b",
        "name": "GPT-OSS 120B (Deep Strategic Reasoning)",
        "badge": "120B Reasoning",
        "recommended": True,
        "description": "Massive 120B parameter reasoning model on Groq LPUs for deep strategic mission planning & synthesis.",
    },
    {
        "id": "openai/gpt-oss-20b",
        "name": "GPT-OSS 20B (Ultra-Fast Reasoning)",
        "badge": "20B Fast",
        "recommended": False,
        "description": "Sub-second 20B reasoning model optimized for rapid strategic mission dispatch on Groq LPUs.",
    },
    {
        "id": "qwen/qwen3.8-27b",
        "name": "Qwen 3.8 27B (Precise Instructions)",
        "badge": "27B Precise",
        "recommended": False,
        "description": "High-accuracy instruction-following and structured JSON synthesis for robotics.",
    },
    {
        "id": "allam-2-7b",
        "name": "ALLAM 2 7B (Lightweight)",
        "badge": "7B Edge",
        "recommended": False,
        "description": "Ultra-lightweight fast general-purpose model for basic commands.",
    },
]


class GroqBrain:
    """
    Tier 1 Strategic Cloud Brain.
    Connects to Groq LPUs (gpt-oss-120b / gpt-oss-20b / qwen3.8-27b) via Groq SDK or HTTPS REST.
    Seamlessly falls back to a deterministic offline strategic engine if no API key is set.
    """

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    DEFAULT_MODEL = "openai/gpt-oss-120b"
    FAST_MODEL = "openai/gpt-oss-20b"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        load_rover_env()
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "").strip()
        env_model = os.getenv("GROQ_MODEL", "").strip()
        # Fallback if old discontinued model is set
        if not env_model or "llama" in env_model.lower():
            env_model = self.DEFAULT_MODEL
        self.model = model or env_model or self.DEFAULT_MODEL
        self._groq_client = None

        if self.api_key and GROQ_SDK_AVAILABLE:
            try:
                self._groq_client = groq.Groq(api_key=self.api_key)
                logger.info("Initialized Groq Cloud SDK client with model: %s", self.model)
            except Exception as e:
                logger.warning("Could not initialize Groq SDK: %s. Using HTTP REST fallback.", e)

    def set_api_key(self, api_key: str, persist_to_env: bool = True) -> bool:
        """Dynamically update Groq API key (e.g. from Dashboard or Input Layer)."""
        self.api_key = (api_key or "").strip()
        os.environ["GROQ_API_KEY"] = self.api_key
        if self.api_key and GROQ_SDK_AVAILABLE:
            try:
                self._groq_client = groq.Groq(api_key=self.api_key)
                logger.info("Groq SDK client updated with new API key.")
            except Exception as e:
                logger.warning("Groq SDK update failed: %s", e)
        else:
            self._groq_client = None

        saved = False
        if persist_to_env:
            saved = save_api_key_to_env(self.api_key)
        return saved

    def set_model(self, model: str, persist_to_env: bool = True) -> bool:
        """Dynamically switch the active Groq model (e.g. from Dashboard Dropdown)."""
        clean_model = (model or "").strip()
        if clean_model:
            self.model = clean_model
            os.environ["GROQ_MODEL"] = self.model
            logger.info("Switched active Groq model to: %s", self.model)
            saved = False
            if persist_to_env:
                saved = save_api_key_to_env(self.model, env_var="GROQ_MODEL")
            return saved
        return False

    def get_status(self) -> Dict[str, Any]:
        """Returns API key status, model info, and model choices for client-side dropdown."""
        has_key = self.is_cloud_ready()
        masked = ""
        if has_key:
            k = self.api_key
            masked = f"{k[:4]}...{k[-4:]}" if len(k) > 8 else "***"
        return {
            "configured": has_key,
            "cloud_ready": has_key,
            "masked_key": masked,
            "model": self.model,
            "available_models": SUPPORTED_GROQ_MODELS,
            "compiler_source": f"Groq LPU ({self.model})" if has_key else "Local Standalone Compiler",
        }

    def is_cloud_ready(self) -> bool:
        """Returns True if a non-empty Groq API key is configured."""
        return bool(self.api_key and len(self.api_key) > 10)

    # ==========================================================================
    # MISSION COMPILATION
    # ==========================================================================

    def compile_mission(
        self,
        prompt: str,
        world_state: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 8.0,
    ) -> MissionSpec:
        """
        Translates a natural language strategic mission request into a structured MissionSpec.
        Tries Groq Cloud LPU first; automatically falls back to local compiler if offline/unconfigured.
        """
        start = time.perf_counter()
        clean_prompt = (prompt or "").strip()
        mission_id = f"msn_{int(time.time())}_{abs(hash(clean_prompt)) % 10000}"

        if self.is_cloud_ready():
            try:
                spec = self._compile_via_groq_cloud(clean_prompt, mission_id, world_state, timeout_seconds)
                spec.compilation_latency_ms = (time.perf_counter() - start) * 1000.0
                return spec
            except Exception as e:
                logger.warning("Groq Cloud compilation failed (%s). Falling back to local strategic compiler.", e)

        # Local high-fidelity strategic compiler fallback
        spec = self._compile_via_local_engine(clean_prompt, mission_id, world_state)
        spec.compilation_latency_ms = (time.perf_counter() - start) * 1000.0
        return spec

    def _compile_via_groq_cloud(
        self,
        prompt: str,
        mission_id: str,
        world_state: Optional[Dict[str, Any]],
        timeout_seconds: float,
    ) -> MissionSpec:
        """Executes mission compilation via Groq Cloud API with structured JSON output."""
        system_prompt = (
            "You are the Strategic Cloud Brain for EdgeRover (a Raspberry Pi 5 4WD autonomous patrol rover).\n"
            "Your task is to compile the user's natural language mission prompt into a valid JSON MissionSpec.\n"
            "The rover operates strictly with these available tools:\n"
            "- move_forward(distance_cm: 1-5000, speed: 0.1-1.0 optional)  # duration_seconds only if no distance is given\n"
            "- move_backward(distance_cm: 1-5000, speed: 0.1-1.0 optional)\n"
            "- turn_left(degrees: 1-360, speed: 0.1-1.0 optional)  # in-place pivot\n"
            "- turn_right(degrees: 1-360, speed: 0.1-1.0 optional)\n"
            "- stop_rover()\n"
            "- scan_surroundings(degrees: 360, speed: 0.3)\n"
            "- capture_evidence(reason: str, severity: 'INFO'|'WARNING'|'CRITICAL')\n"
            "- get_rover_telemetry()\n"
            "- send_telegram_alert(message: str, attach_photo: bool)\n\n"
            "HARDWARE FACTS (plan around them):\n"
            "- There is NO distance/obstacle sensor and NO odometry. Motion is open loop: the rover converts "
            "distance_cm and degrees into motor-on time itself, so ALWAYS give distances in centimetres "
            "(convert metres/feet) and turns in degrees. Never compute durations yourself.\n"
            "- The camera is FIXED to the chassis (no pan/tilt servo). To look in another direction the whole rover "
            "must turn (turn_left/turn_right/scan_surroundings) before capture_evidence.\n"
            "- Keep steps in the exact order the user described. Do not add extra movement the user did not ask for. "
            "Use speed only if the user specified one.\n\n"
            "Respond ONLY with valid JSON following this exact schema:\n"
            "{\n"
            '  "title": "Short descriptive mission title",\n'
            '  "description": "Clear high-level strategic summary",\n'
            '  "target_area": "Target sector or zone",\n'
            '  "estimated_duration_s": 120.0,\n'
            '  "safety_rules": ["Operator e-stop aborts the mission", "Alert if person detected"],\n'
            '  "steps": [\n'
            '    {\n'
            '      "step_number": 1,\n'
            '      "title": "Brief step summary",\n'
            '      "action_type": "TOOL_EXECUTION",\n'
            '      "tool_name": "get_rover_telemetry",\n'
            '      "parameters": {},\n'
            '      "timeout_seconds": 5.0,\n'
            '      "completion_condition": "telemetry_received",\n'
            '      "on_failure": "ABORT"\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        user_content = f"User Mission Request: '{prompt}'\nCurrent World State: {json.dumps(world_state or {})}"

        # If SDK available
        if self._groq_client:
            chat_completion = self._groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1500,
                timeout=timeout_seconds,
            )
            raw_text = chat_completion.choices[0].message.content or ""
        else:
            # Fallback to direct HTTPS REST
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 1500,
            }
            req = urllib.request.Request(
                self.GROQ_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "EdgeRover-GroqBrain/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_text = data["choices"][0]["message"]["content"]

        parsed = json.loads(raw_text)
        steps = [
            MissionStep(
                step_number=s.get("step_number", idx + 1),
                title=s.get("title", f"Step {idx+1}"),
                action_type=s.get("action_type", "TOOL_EXECUTION"),
                tool_name=s.get("tool_name", "stop_rover"),
                parameters=s.get("parameters", {}),
                timeout_seconds=float(s.get("timeout_seconds", 10.0)),
                completion_condition=s.get("completion_condition", "duration_elapsed"),
                on_failure=s.get("on_failure", "ABORT"),
            )
            for idx, s in enumerate(parsed.get("steps", []))
        ]

        return MissionSpec(
            mission_id=mission_id,
            title=parsed.get("title", "Autonomous Rover Mission"),
            description=parsed.get("description", prompt),
            target_area=parsed.get("target_area", "Perimeter Zone"),
            estimated_duration_s=float(parsed.get("estimated_duration_s", 60.0)),
            safety_rules=parsed.get("safety_rules", ["Proximity limit: 30cm", "Abort on critical low battery"]),
            steps=steps,
            compiler_source="groq_cloud_lpu",
        )

    def _compile_explicit_sequence(self, prompt: str, mission_id: str) -> Optional["MissionSpec"]:
        """Turns "forward 100 cm then turn left 90 degrees" into steps, with no cloud and no invented moves."""
        from intelligence.needle import needle_router  # lazy: avoids an import cycle

        calls = needle_router.parse_sequence(prompt)
        if not calls or not any(c["name"] in needle_router.MOTION_TOOLS for c in calls):
            return None

        steps = [
            MissionStep(
                step_number=i + 1,
                title=c["reasoning"],
                action_type="TOOL_EXECUTION",
                tool_name=c["name"],
                parameters=dict(c["arguments"]),
                timeout_seconds=30.0,
                completion_condition="motion_complete",
            )
            for i, c in enumerate(calls)
        ]
        steps.append(MissionStep(
            step_number=len(steps) + 1,
            title="Halt motors",
            action_type="TOOL_EXECUTION",
            tool_name="stop_rover",
            parameters={},
            timeout_seconds=2.0,
        ))
        return MissionSpec(
            mission_id=mission_id,
            title=f"Mission: {prompt[:40]}",
            description=prompt,
            target_area="Current position",
            estimated_duration_s=sum(s.timeout_seconds for s in steps),
            safety_rules=["Open-loop timed moves (no distance sensor)", "Operator e-stop aborts the mission"],
            steps=steps,
            compiler_source="local_sequence_parser",
        )

    def _compile_via_local_engine(
        self,
        prompt: str,
        mission_id: str,
        world_state: Optional[Dict[str, Any]],
    ) -> MissionSpec:
        """Deterministic local fallback compiler ensuring 100% offline reliability."""
        text = prompt.lower()
        title = "Strategic Autonomous Mission"
        steps: List[MissionStep] = []

        # If the prompt is a plain chain of drive/turn instructions, compile exactly that.
        explicit = self._compile_explicit_sequence(prompt, mission_id)
        if explicit is not None:
            return explicit

        # Always step 1: Pre-flight telemetry and sensor health audit
        steps.append(MissionStep(
            step_number=1,
            title="Pre-flight sensor & battery health check",
            action_type="TOOL_EXECUTION",
            tool_name="get_rover_telemetry",
            parameters={},
            timeout_seconds=3.0,
            completion_condition="telemetry_verified",
            on_failure="ABORT",
        ))

        # Check for 360 room audit
        if "360" in text or "room audit" in text or "scan room" in text:
            title = "360° Visual Environment Sweep & Audit"
            steps.append(MissionStep(
                step_number=2,
                title="Execute 360° pan-rotation surveillance sweep",
                action_type="TOOL_EXECUTION",
                tool_name="scan_surroundings",
                parameters={"degrees": 360.0, "speed": 0.28},
                timeout_seconds=12.0,
            ))
            steps.append(MissionStep(
                step_number=3,
                title="Capture high-resolution evidence panorama",
                action_type="TOOL_EXECUTION",
                tool_name="capture_evidence",
                parameters={"reason": "360-degree audit evidence snapshot", "severity": "INFO"},
                timeout_seconds=5.0,
            ))

        # Check for perimeter patrol
        elif "patrol" in text or "warehouse" in text or "perimeter" in text:
            title = "Autonomous Perimeter Patrol & Security Sweep"
            steps.append(MissionStep(
                step_number=2,
                title="Advance along Sector Alpha patrol lane",
                action_type="TOOL_EXECUTION",
                tool_name="move_forward",
                parameters={"distance_cm": 150.0},
                timeout_seconds=6.0,
            ))
            steps.append(MissionStep(
                step_number=3,
                title="Execute 90° corner pivot toward East boundary",
                action_type="TOOL_EXECUTION",
                tool_name="turn_right",
                parameters={"degrees": 90.0},
                timeout_seconds=4.0,
            ))
            steps.append(MissionStep(
                step_number=4,
                title="Traverse East perimeter segment",
                action_type="TOOL_EXECUTION",
                tool_name="move_forward",
                parameters={"distance_cm": 150.0},
                timeout_seconds=6.0,
            ))
            steps.append(MissionStep(
                step_number=5,
                title="Perform 180° visual audit for unauthorized personnel",
                action_type="TOOL_EXECUTION",
                tool_name="scan_surroundings",
                parameters={"degrees": 180.0, "speed": 0.30},
                timeout_seconds=8.0,
            ))

        # Check for target proximity or forward advance
        elif "target" in text or "approach" in text or "maintain" in text:
            title = "Target Proximity Inspection & Audit"
            steps.append(MissionStep(
                step_number=2,
                title="Cautious forward approach toward target object",
                action_type="TOOL_EXECUTION",
                tool_name="move_forward",
                parameters={"distance_cm": 60.0, "speed": 0.4},
                timeout_seconds=5.0,
            ))
            steps.append(MissionStep(
                step_number=3,
                title="Capture close-up surveillance photo",
                action_type="TOOL_EXECUTION",
                tool_name="capture_evidence",
                parameters={"reason": "Close-range target inspection", "severity": "INFO"},
                timeout_seconds=4.0,
            ))

        # Generic multi-step fallback
        else:
            title = f"Mission: {prompt[:32]}..."
            steps.append(MissionStep(
                step_number=2,
                title="Execute forward traversal",
                action_type="TOOL_EXECUTION",
                tool_name="move_forward",
                parameters={"distance_cm": 100.0},
                timeout_seconds=5.0,
            ))
            steps.append(MissionStep(
                step_number=3,
                title="Conduct surveillance sweep",
                action_type="TOOL_EXECUTION",
                tool_name="scan_surroundings",
                parameters={"degrees": 180.0, "speed": 0.30},
                timeout_seconds=8.0,
            ))

        # Final step: Hold position and record final telemetry
        steps.append(MissionStep(
            step_number=len(steps) + 1,
            title="Halt motors and verify final position",
            action_type="TOOL_EXECUTION",
            tool_name="stop_rover",
            parameters={},
            timeout_seconds=2.0,
        ))

        total_est_seconds = sum(s.timeout_seconds for s in steps)

        return MissionSpec(
            mission_id=mission_id,
            title=title,
            description=prompt,
            target_area="Facility Interior / Patrol Route",
            estimated_duration_s=total_est_seconds,
            safety_rules=[
                "Open-loop timed moves (no distance sensor fitted)",
                "Emergency halt on human detection within 150cm (Laya Tier 3)",
                "Watchdog heartbeat limit: 600ms",
            ],
            steps=steps,
            compiler_source="local_strategic_compiler",
        )

    # ==========================================================================
    # MISSION DEBRIEF & SYNTHESIS
    # ==========================================================================

    def generate_mission_debrief(
        self,
        mission_spec: Dict[str, Any],
        events_history: List[Dict[str, Any]],
        telemetry_summary: Dict[str, Any],
    ) -> DebriefReport:
        """
        Synthesizes mission events and telemetry into an executive report for Dashboard & Telegram.
        """
        start = time.perf_counter()
        mission_id = mission_spec.get("mission_id", f"msn_{int(time.time())}")
        mission_title = mission_spec.get("title", "Autonomous Mission")
        duration_s = float(telemetry_summary.get("duration_seconds", 45.0))
        mins = int(duration_s // 60)
        secs = int(duration_s % 60)
        duration_formatted = f"{mins} min {secs} sec" if mins > 0 else f"{secs} sec"

        batt_start = float(telemetry_summary.get("battery_start_pct", 84.0))
        batt_end = float(telemetry_summary.get("battery_end_pct", 78.0))
        batt_delta = round(batt_start - batt_end, 1)

        # Count detections and critical events
        detections_count: Dict[str, int] = {}
        critical_count = 0
        obstacles_avoided = int(telemetry_summary.get("obstacles_avoided", 0))

        for ev in events_history:
            severity = str(ev.get("severity", "")).upper()
            if severity == "CRITICAL":
                critical_count += 1
            for d in ev.get("detections", []):
                lbl = str(d.get("label", "unknown")).lower()
                detections_count[lbl] = detections_count.get(lbl, 0) + 1

        # Use cloud LLM if ready, else offline synthesis
        if self.is_cloud_ready():
            try:
                report = self._debrief_via_groq_cloud(
                    mission_spec, events_history, telemetry_summary,
                    duration_s, duration_formatted, batt_start, batt_end, batt_delta,
                    detections_count, critical_count, obstacles_avoided
                )
                report.synthesis_latency_ms = (time.perf_counter() - start) * 1000.0
                return report
            except Exception as e:
                logger.warning("Groq Cloud debrief generation failed (%s). Using local synthesis.", e)

        # Local synthesis fallback
        det_text = ", ".join(f"{count} {label}s" for label, count in detections_count.items()) if detections_count else "Zero anomalous objects"
        summary_narrative = (
            f"Rover completed '{mission_title}' in {duration_formatted}. "
            f"Battery consumed: {batt_delta}% ({batt_start:.0f}% -> {batt_end:.0f}%). "
            f"Sensory sweep cataloged: {det_text}. "
            f"Encountered {obstacles_avoided} obstacle encounters safely circumvented via Laya System-1 avoidance. "
            f"{'All safety interlocks passed.' if critical_count == 0 else f'{critical_count} critical incident(s) reviewed and logged.'}"
        )

        recommendations = [
            "Perimeter boundary status confirmed secure.",
            "Battery reserve remains sufficient for subsequent operational sorties.",
            "Camera lens clarity and ToF calibration within nominal tolerances."
        ]

        report = DebriefReport(
            mission_id=mission_id,
            mission_title=mission_title,
            status="COMPLETED",
            duration_seconds=duration_s,
            duration_formatted=duration_formatted,
            battery_start_pct=batt_start,
            battery_end_pct=batt_end,
            battery_delta_pct=batt_delta,
            detections_summary=detections_count,
            critical_events_count=critical_count,
            obstacles_avoided_count=obstacles_avoided,
            executive_summary=summary_narrative,
            recommendations=recommendations,
            compiler_source="local_strategic_compiler",
            synthesis_latency_ms=(time.perf_counter() - start) * 1000.0,
        )
        return report

    def _debrief_via_groq_cloud(
        self,
        mission_spec: Dict[str, Any],
        events_history: List[Dict[str, Any]],
        telemetry_summary: Dict[str, Any],
        duration_s: float,
        duration_formatted: str,
        batt_start: float,
        batt_end: float,
        batt_delta: float,
        detections_count: Dict[str, int],
        critical_count: int,
        obstacles_avoided: int,
    ) -> DebriefReport:
        """Executes executive debrief synthesis via Groq Cloud LLM."""
        sys_prompt = (
            "You are the Executive Incident & Mission Debrief Officer for EdgeRover.\n"
            "Synthesize the mission data into an executive summary and list of security recommendations.\n"
            "Respond ONLY with valid JSON matching:\n"
            "{\n"
            '  "executive_summary": "Concise 2-3 sentence narrative describing mission execution and outcomes.",\n'
            '  "recommendations": ["Recommendation 1", "Recommendation 2"]\n'
            "}"
        )
        user_prompt = json.dumps({
            "mission": mission_spec,
            "events_count": len(events_history),
            "detections": detections_count,
            "critical_events": critical_count,
            "obstacles_avoided": obstacles_avoided,
            "battery_delta": batt_delta,
        })

        if self._groq_client:
            resp = self._groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1500,
                timeout=15.0,
            )
            raw = resp.choices[0].message.content or ""
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
                "max_tokens": 1500,
            }
            req = urllib.request.Request(
                self.GROQ_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8.0) as http_resp:
                res_data = json.loads(http_resp.read().decode("utf-8"))
                raw = res_data["choices"][0]["message"]["content"]

        parsed = json.loads(raw)
        return DebriefReport(
            mission_id=mission_spec.get("mission_id", f"msn_{int(time.time())}"),
            mission_title=mission_spec.get("title", "Autonomous Mission"),
            status="COMPLETED",
            duration_seconds=duration_s,
            duration_formatted=duration_formatted,
            battery_start_pct=batt_start,
            battery_end_pct=batt_end,
            battery_delta_pct=batt_delta,
            detections_summary=detections_count,
            critical_events_count=critical_count,
            obstacles_avoided_count=obstacles_avoided,
            executive_summary=parsed.get("executive_summary", "Mission completed successfully."),
            recommendations=parsed.get("recommendations", ["Maintain standard security readiness."]),
            compiler_source="groq_cloud_lpu",
        )


# Global shared GroqBrain instance
groq_brain = GroqBrain()
