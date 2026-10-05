"""
EdgeRover — Needle 2 Edge Tool Calling SLM & Semantic Router (Tier 2).

Integrates with Cactus Compute Needle (https://github.com/cactus-compute/needle):
- Foundation model for tiny devices (8-29 MB binary, 2-bit, tool calls on robots/microcontrollers).
- Supports native `import needle` and `needle.Needle(tools=..., generation=2)`.
- If `cactus-needle` is installed, routes directly through the Cactus Needle runtime.
- Includes a built-in deterministic SLM slot-filling fallback engine guaranteeing sub-10ms
  latency and zero cloud dependency on any development laptop or Raspberry Pi.
- Automatically detects complex multi-step strategic missions and escalates them to Tier 1 Groq.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from intelligence.tools import (
    CANONICAL_TOOL_FUNCTIONS,
    ToolExecutionResult,
    ToolRegistry,
    tool_registry,
)

logger = logging.getLogger("NeedleRouter")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [Needle-SLM] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Check for cactus-needle package
try:
    import needle
    CACTUS_NEEDLE_AVAILABLE = True
    logger.info("Found cactus-needle package installed.")
except ImportError:
    CACTUS_NEEDLE_AVAILABLE = False
    logger.info("cactus-needle package not installed. Using high-speed embedded Needle engine.")


@dataclass
class NeedleCommandResult:
    """Standardized result of Needle edge natural language parsing and tool dispatch."""
    success: bool
    prompt: str
    action: str                        # "execute_tool", "escalate_to_groq", "rejected"
    tier: str                          # "needle_edge" or "groq_cloud"
    tool_called: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    latency_ms: float = 0.0
    function_calls: List[Dict[str, Any]] = field(default_factory=list)
    results: List[Any] = field(default_factory=list)
    reasoning: str = ""
    engine: str = "embedded_needle_slm" # "cactus_needle_v2" or "embedded_needle_slm"
    execution_result: Optional[ToolExecutionResult] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "prompt": self.prompt,
            "action": self.action,
            "tier": self.tier,
            "tool_called": self.tool_called,
            "parameters": self.parameters,
            "confidence": round(self.confidence, 3),
            "latency_ms": round(self.latency_ms, 2),
            "function_calls": self.function_calls,
            "results": self.results,
            "reasoning": self.reasoning,
            "engine": self.engine,
            "execution_result": self.execution_result.to_dict() if self.execution_result else None,
            "message": self.message,
        }


class NeedleRouter:
    """
    Tier 2 Edge Tool Dispatcher.
    Wraps Cactus Compute Needle model or uses embedded slot-filling engine.
    Returns standard Cactus Needle format: `function_calls`, `results`, `reasoning`, `confidence`.
    """

    STRATEGIC_MISSION_CUES = [
        "patrol", "survey", "inspect", "guard", "mission", "perimeter",
        "search for", "find all", "track down", "loop", "until", "every",
        "schedule", "return to base", "dock", "audit", "report back when"
    ]

    def __init__(self, registry: Optional[ToolRegistry] = None, use_cactus: bool = True):
        self.registry = registry or tool_registry
        self.default_speed = 0.35
        self._dispatch_count = 0
        self._total_latency_ms = 0.0

        self.cactus_agent = None
        if use_cactus and CACTUS_NEEDLE_AVAILABLE:
            try:
                # Needle 3 initialization per cactus-compute docs (stateless=True avoids multi-turn drift)
                self.cactus_agent = needle.Needle(tools=CANONICAL_TOOL_FUNCTIONS, stateless=True)
                logger.info("Initialized Cactus Compute Needle 3 agent with registered rover tools (stateless=True).")
            except Exception as e:
                logger.warning("Could not initialize cactus.Needle: %s. Using embedded engine.", e)

    def is_complex_mission(self, prompt: str) -> bool:
        """Determines if the prompt requires Tier 1 Groq multi-step strategic compilation."""
        text = prompt.lower()
        has_strategic_cue = any(cue in text for cue in self.STRATEGIC_MISSION_CUES)
        is_multi_step = (" and then " in text or " then " in text or " after that " in text or ";" in text)
        is_long_prompt = len(text.split()) > 10
        return has_strategic_cue or (is_multi_step and is_long_prompt)

    # ==========================================================================
    # CACTUS-NEEDLE EMBEDDED ENGINE (Slot Filling & Regex Grammar)
    # ==========================================================================

    _NUMBER_WORDS = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    }
    _DIST_RE = re.compile(
        r'(\d+(?:\.\d+)?)\s*(centimeters?|centimetres?|cms?|millimeters?|millimetres?|mm|'
        r'meters?|metres?|m|feet|foot|ft|inches|inch)\b'
    )
    _SPLIT_RE = re.compile(
        r'\s*(?:[,;]|\band then\b|\bthen\b|\bafter that\b|\bafterwards\b|\bnext\b|\band\b)\s*'
    )
    MOTION_TOOLS = ("move_forward", "move_backward", "turn_left", "turn_right", "scan_surroundings")

    def _normalize(self, text: str) -> str:
        clean = text.lower().strip()
        for word, digit in self._NUMBER_WORDS.items():
            clean = re.sub(rf'\b{word}\b', digit, clean)
        return clean

    def _extract_distance_cm(self, text: str) -> Optional[float]:
        match = self._DIST_RE.search(text)
        if not match:
            return None
        value, unit = float(match.group(1)), match.group(2)
        if unit.startswith(("centi", "cm")):
            factor = 1.0
        elif unit.startswith(("milli", "mm")):
            factor = 0.1
        elif unit.startswith(("meter", "metre")) or unit == "m":
            factor = 100.0
        elif unit.startswith("f"):
            factor = 30.48
        else:
            factor = 2.54
        return max(1.0, min(5000.0, value * factor))

    def _extract_duration(self, text: str, default: float = 1.0) -> float:
        match_ms = re.search(r'(\d+(?:\.\d+)?)\s*(?:ms|milliseconds)\b', text)
        if match_ms:
            return max(0.1, float(match_ms.group(1)) / 1000.0)

        match_s = re.search(r'(\d+(?:\.\d+)?)\s*(?:s|secs?|seconds?)\b', text)
        if match_s:
            return min(60.0, max(0.1, float(match_s.group(1))))

        match_num = re.search(r'(?:for|duration)\s+(\d+(?:\.\d+)?)\b(?!\s*(?:cm|mm|m|ft|deg|%))', text)
        if match_num:
            return min(60.0, max(0.1, float(match_num.group(1))))

        return default

    def _extract_speed(self, text: str, default: Optional[float] = 0.35) -> Optional[float]:
        if re.search(r'\b(slow|slowly|creeping)\b', text):
            return 0.40
        if re.search(r'\b(fast|quick|quickly|rapid)\b', text):
            return 0.75
        if re.search(r'\bmax\b|full speed', text):
            return 1.00

        match_pct = re.search(r'(\d{1,3})\s*%', text)
        if match_pct:
            pct = float(match_pct.group(1))
            return max(0.10, min(1.00, pct / 100.0))

        match_speed = re.search(r'(?:speed|throttle|power)\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)', text)
        if match_speed:
            val = float(match_speed.group(1))
            if val > 1.0:
                val = val / 100.0
            return max(0.10, min(1.00, val))

        return default

    def _extract_degrees(self, text: str, default: float = 90.0) -> float:
        match_deg = re.search(r'(\d+(?:\.\d+)?)\s*(?:deg|degrees|degree|°)', text)
        if match_deg:
            return max(1.0, min(360.0, float(match_deg.group(1))))

        if re.search(r'u-?turn|turn around|about[- ]face|\b180\b', text):
            return 180.0
        if re.search(r'full spin|full circle|\b360\b', text):
            return 360.0
        if "quarter" in text:
            return 90.0
        if "half" in text:
            return 180.0

        return default

    def _with_speed(self, params: Dict[str, Any], clean: str) -> Dict[str, Any]:
        speed = self._extract_speed(clean, default=None)
        if speed is not None:
            params["speed"] = speed
        return params

    def parse_command(self, prompt: str) -> Tuple[Optional[str], Dict[str, Any], float, str]:
        """
        Extracts tool name, parameters, confidence, and reasoning from prompt.
        Distances/angles are passed through unchanged; the motion controller turns
        them into motor-on time using the rover's calibration.
        """
        clean = self._normalize(prompt)
        if not clean:
            return None, {}, 0.0, "Empty instruction."

        # 1. Stop / Halt
        if re.search(r'\b(stop|halt|brake|freeze|kill|abort)\b|cut motors', clean):
            return "stop_rover", {}, 0.99, "Emergency stop requested."

        distance_cm = self._extract_distance_cm(clean)
        has_turn_word = re.search(r'\b(turn|spin|rotate|pivot|steer|face|go|head|veer)\b', clean) is not None

        # 2. Turns (checked before forward so "turn left 90 degrees" is never read as a drive)
        for side in ("left", "right"):
            if re.search(rf'\b{side}\b', clean) and has_turn_word and distance_cm is None:
                degrees = self._extract_degrees(clean, default=90.0)
                params = self._with_speed({"degrees": degrees}, clean)
                return f"turn_{side}", params, 0.94, f"Pivot {side} {degrees:g}°"

        if re.search(r'u-?turn|turn around|about[- ]face', clean):
            return "turn_right", self._with_speed({"degrees": 180.0}, clean), 0.9, "Turn around (180° clockwise)"

        # 3. Backward / Reverse
        if re.search(r'backward|backwards|back up|reverse|reversing|retreat|\bback\b', clean):
            return self._linear_call("move_backward", clean, distance_cm, "Reverse")

        # 4. Forward
        if (re.search(r'forward|ahead|straight|advance|drive on', clean)
                or (distance_cm is not None and re.search(r'\b(go|move|drive|walk|travel|run)\b', clean))):
            return self._linear_call("move_forward", clean, distance_cm, "Drive forward")

        # 5. Surroundings Scan
        if any(w in clean for w in ["scan", "sweep", "look around", "360"]):
            degrees = self._extract_degrees(clean, default=360.0)
            return ("scan_surroundings", self._with_speed({"degrees": degrees}, clean), 0.92,
                    f"Rotate the whole rover {degrees:g}° (camera is fixed)")

        # 6. Capture Evidence
        if any(w in clean for w in ["photo", "snapshot", "picture", "capture", "evidence", "record snapshot"]):
            reason = prompt
            for prefix in ["take a photo of", "capture evidence of", "snap picture of", "take photo", "capture photo"]:
                if prefix in clean:
                    idx = clean.find(prefix) + len(prefix)
                    sub = prompt[idx:].strip()
                    if sub:
                        reason = sub
                        break

            severity = "INFO"
            if any(w in clean for w in ["critical", "emergency", "intruder", "danger", "breach"]):
                severity = "CRITICAL"
            elif any(w in clean for w in ["warning", "alert", "anomaly", "caution"]):
                severity = "WARNING"

            return "capture_evidence", {"reason": reason, "severity": severity}, 0.93, f"Capture snapshot for '{reason}' ({severity})"

        # 7. Telemetry
        if any(w in clean for w in ["telemetry", "battery", "status", "health", "sensors", "distance", "readings", "diagnostics"]):
            return "get_rover_telemetry", {}, 0.96, "Retrieve current telemetry"

        # 8. Alert Telegram
        if any(w in clean for w in ["telegram", "send alert", "notify security", "dispatch alert"]):
            return "send_telegram_alert", {"message": prompt, "attach_photo": True}, 0.91, "Dispatch security notification"

        return None, {}, 0.0, "No matching edge tool found."

    def _linear_call(self, tool: str, clean: str, distance_cm: Optional[float], verb: str):
        if distance_cm is not None:
            params: Dict[str, Any] = {"distance_cm": round(distance_cm, 1)}
            why = f"{verb} {distance_cm:g} cm"
        else:
            duration = self._extract_duration(clean, default=1.0)
            params = {"duration_seconds": duration}
            why = f"{verb} for {duration:g}s"
        return tool, self._with_speed(params, clean), 0.95, why

    # ==========================================================================
    # MULTI-STEP SEQUENCES ("go forward 100 cm then turn left 90 degrees")
    # ==========================================================================

    def has_strategic_cue(self, prompt: str) -> bool:
        text = prompt.lower()
        return any(cue in text for cue in self.STRATEGIC_MISSION_CUES)

    def parse_sequence(self, prompt: str) -> Optional[List[Dict[str, Any]]]:
        """Splits a prompt into ordered tool calls. Returns None unless EVERY part is understood."""
        clean = self._normalize(prompt)
        parts = [p.strip() for p in self._SPLIT_RE.split(clean) if p and p.strip()]
        parts = [re.sub(r'^(?:first|finally|lastly|please|also)\s+', '', p) for p in parts]
        parts = [p for p in parts if p]

        calls: List[Dict[str, Any]] = []
        for part in parts:
            tool, params, _conf, why = self.parse_command(part)
            if not tool:
                return None
            calls.append({"name": tool, "arguments": params, "text": part, "reasoning": why})

        if len(calls) > 1:
            # Every queued move already ends with a motor stop; a "stop" inside a sequence is redundant.
            calls = [c for c in calls if c["name"] != "stop_rover"] or calls[:1]
        return calls or None

    def _dispatch_sequence(self, prompt: str, calls: List[Dict[str, Any]], execute: bool, start: float) -> NeedleCommandResult:
        results_list: List[Dict[str, Any]] = []
        last_exec: Optional[ToolExecutionResult] = None
        success = True
        total_s = 0.0
        if execute:
            for call in calls:
                res = self.registry.execute(call["name"], dict(call["arguments"]))
                last_exec = res
                results_list.append(res.to_dict())
                if not res.success:
                    success = False
                    break
                if isinstance(res.output, dict):
                    total_s += float(res.output.get("duration_s") or 0.0)

        latency = (time.perf_counter() - start) * 1000.0
        self._dispatch_count += 1
        self._total_latency_ms += latency

        summary = " -> ".join(c["reasoning"] for c in calls)
        if not success and last_exec is not None:
            message = f"Could not run '{last_exec.tool_name}': {last_exec.error}"
        elif total_s:
            message = f"Queued {len(calls)} step(s), about {total_s:.1f}s total: {summary}"
        else:
            message = f"Dispatched: {summary}"

        return NeedleCommandResult(
            success=success,
            prompt=prompt,
            action="execute_tool",
            tier="needle_edge",
            tool_called=" -> ".join(c["name"] for c in calls),
            parameters={"steps": [{"name": c["name"], "arguments": c["arguments"]} for c in calls]},
            confidence=0.95,
            latency_ms=latency,
            function_calls=[{"name": c["name"], "arguments": c["arguments"]} for c in calls],
            results=results_list,
            reasoning=summary,
            engine="embedded_needle_slm",
            execution_result=last_exec,
            message=message,
        )

    # ==========================================================================
    # CACTUS COMPUTE NEEDLE .run() INTERFACE COMPATIBILITY
    # ==========================================================================

    def run(self, prompt: str) -> Dict[str, Any]:
        """
        Direct compatibility with `agent = needle.Needle(tools=[...]); agent.run(...)`
        Returns dict with `function_calls`, `results`, `reasoning`, `confidence`.
        """
        dispatch_res = self.dispatch(prompt, execute=True)
        return {
            "function_calls": dispatch_res.function_calls,
            "results": dispatch_res.results,
            "reasoning": dispatch_res.reasoning,
            "confidence": dispatch_res.confidence,
            "latency_ms": dispatch_res.latency_ms,
        }

    # ==========================================================================
    # FULL DISPATCH PIPELINE
    # ==========================================================================

    def dispatch(self, prompt: str, execute: bool = True) -> NeedleCommandResult:
        """
        Executes natural language instruction via Cactus Needle or embedded SLM engine.
        """
        start = time.perf_counter()
        clean = (prompt or "").strip()

        if not clean:
            latency = (time.perf_counter() - start) * 1000.0
            return NeedleCommandResult(
                success=False,
                prompt=prompt,
                action="rejected",
                tier="needle_edge",
                latency_ms=latency,
                message="Empty instruction prompt."
            )

        # Step 0: Deterministic edge parsing of plain motion commands and chains of them
        # ("go forward 100 cm then turn left 90 degrees"). Distances and angles are exact,
        # so this beats both the cloud and the tiny model for open-loop driving.
        short_stop = len(clean.split()) <= 4 and self.parse_command(clean)[0] == "stop_rover"
        if short_stop or not self.has_strategic_cue(clean):
            calls = self.parse_sequence(clean)
            if calls and (len(calls) > 1 or calls[0]["name"] in self.MOTION_TOOLS + ("stop_rover",)):
                return self._dispatch_sequence(prompt, calls, execute, start)

        # Step 1: Check if instruction requires Tier 1 Groq strategic mission compilation
        if self.is_complex_mission(clean):
            latency = (time.perf_counter() - start) * 1000.0
            self._dispatch_count += 1
            self._total_latency_ms += latency
            return NeedleCommandResult(
                success=True,
                prompt=prompt,
                action="escalate_to_groq",
                tier="groq_cloud",
                confidence=0.98,
                latency_ms=latency,
                reasoning="Instruction contains multi-step or strategic patrol objectives.",
                message=f"Needle identified '{prompt}' as a multi-step mission. Escalating to Tier 1 Cloud Brain (Groq)."
            )

        # Step 2: Try Cactus Needle if available
        if self.cactus_agent is not None:
            try:
                cactus_out = self.cactus_agent.run(clean)
                func_calls = cactus_out.get("function_calls", [])
                results = cactus_out.get("results", [])
                reasoning = cactus_out.get("reasoning", "")
                conf = float(cactus_out.get("confidence", 0.95))

                tool_name = None
                params = {}

                # Needle may directly execute the tool and return the output in results
                if results and len(results) > 0:
                    first_res = results[0]
                    if isinstance(first_res, dict):
                        tool_name = first_res.get("tool_name")
                        params = first_res.get("arguments", {})

                # Or Needle may output structured function_calls
                if not tool_name and func_calls and len(func_calls) > 0:
                    tool_name = func_calls[0].get("name")
                    params = func_calls[0].get("arguments", {})

                # Auto-normalize speed percentage to fraction (e.g. 40.0 -> 0.40)
                if params and isinstance(params, dict):
                    for k, v in list(params.items()):
                        if "speed" in k.lower() and isinstance(v, (int, float)) and v > 1.0:
                            params[k] = min(round(v / 100.0, 2), 1.0)

                latency = (time.perf_counter() - start) * 1000.0
                self._dispatch_count += 1
                self._total_latency_ms += latency

                if tool_name:
                    exec_result = None
                    if execute and not results:
                        exec_result = self.registry.execute(tool_name, params)
                    elif results and isinstance(results[0], dict) and "success" in results[0]:
                        r0 = results[0]
                        exec_result = ToolExecutionResult(
                            success=r0.get("success", True),
                            tool_name=tool_name,
                            arguments=params,
                            output=r0.get("output"),
                            error=r0.get("error"),
                            execution_time_ms=latency,
                        )

                    return NeedleCommandResult(
                        success=True,
                        prompt=prompt,
                        action="execute_tool",
                        tier="needle_edge",
                        tool_called=tool_name,
                        parameters=params,
                        confidence=conf,
                        latency_ms=latency,
                        function_calls=func_calls,
                        results=results,
                        reasoning=reasoning,
                        engine="cactus_needle_v3",
                        execution_result=exec_result,
                        message=f"Cactus Needle 3 dispatched '{tool_name}' in {latency:.2f}ms."
                    )
            except Exception as e:
                logger.warning("Cactus Needle run exception (%s). Falling back to embedded engine.", e)

        # Step 3: Embedded SLM Engine
        tool_name, params, conf, reasoning = self.parse_command(clean)

        if not tool_name:
            latency = (time.perf_counter() - start) * 1000.0
            return NeedleCommandResult(
                success=True,
                prompt=prompt,
                action="escalate_to_groq",
                tier="groq_cloud",
                confidence=0.75,
                latency_ms=latency,
                reasoning=reasoning,
                engine="embedded_needle_slm",
                message=f"Ambiguous instruction '{clean}'. Escalating to Groq LLM for reasoning."
            )

        # Execute tool via registry
        exec_result: Optional[ToolExecutionResult] = None
        results_list = []
        if execute:
            exec_result = self.registry.execute(tool_name, params)
            success = exec_result.success
            results_list = [exec_result.to_dict()]
        else:
            success = True

        latency = (time.perf_counter() - start) * 1000.0
        self._dispatch_count += 1
        self._total_latency_ms += latency

        func_calls = [{"name": tool_name, "arguments": params}]

        return NeedleCommandResult(
            success=success,
            prompt=prompt,
            action="execute_tool",
            tier="needle_edge",
            tool_called=tool_name,
            parameters=params,
            confidence=conf,
            latency_ms=latency,
            function_calls=func_calls,
            results=results_list,
            reasoning=reasoning,
            engine="embedded_needle_slm",
            execution_result=exec_result,
            message=f"Needle dispatched '{tool_name}' locally in {latency:.2f}ms."
        )

    def get_average_latency_ms(self) -> float:
        if self._dispatch_count == 0:
            return 0.0
        return self._total_latency_ms / self._dispatch_count


# Global shared Needle instance
needle_router = NeedleRouter()
