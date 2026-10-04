"""
EdgeRover — Typed Tool Registry & Function Calling Schemas (PRD Section 8).

Defines the strictly typed interface for both Needle 2 (Edge SLM) and Groq (Cloud LLM)
to interact with rover actuators, sensors, vision perception, and alerting pipelines.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("RoverToolRegistry")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [ToolRegistry] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclass
class ToolExecutionResult:
    """Standardized result returned by all rover tool executions."""
    success: bool
    tool_name: str
    arguments: Dict[str, Any]
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "timestamp": self.timestamp,
        }


# ==============================================================================
# CANONICAL ROVER TOOLS (PRD Section 8)
# ==============================================================================

ROVER_TOOLS_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "move_forward",
        "description": "Drive rover forward for a specific duration or until stopped.",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 1.0,
                    "default": 0.35,
                    "description": "Motor throttle speed fraction between 0.1 and 1.0."
                },
                "duration_seconds": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 60.0,
                    "default": 1.0,
                    "description": "Drive duration in seconds before halting."
                }
            },
            "required": ["duration_seconds"]
        }
    },
    {
        "name": "move_backward",
        "description": "Drive rover in reverse for a specific duration.",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 1.0,
                    "default": 0.30,
                    "description": "Motor reverse throttle speed fraction between 0.1 and 1.0."
                },
                "duration_seconds": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 30.0,
                    "default": 1.0,
                    "description": "Reverse drive duration in seconds before halting."
                }
            },
            "required": ["duration_seconds"]
        }
    },
    {
        "name": "turn_left",
        "description": "Pivot or spin rover counter-clockwise to the left.",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 1.0,
                    "default": 0.35,
                    "description": "Turn throttle speed."
                },
                "degrees": {
                    "type": "number",
                    "minimum": 1.0,
                    "maximum": 360.0,
                    "default": 90.0,
                    "description": "Approximate angular rotation degrees to turn."
                },
                "duration_seconds": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 10.0,
                    "default": 0.6,
                    "description": "Optional rotation duration in seconds."
                }
            }
        }
    },
    {
        "name": "turn_right",
        "description": "Pivot or spin rover clockwise to the right.",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 1.0,
                    "default": 0.35,
                    "description": "Turn throttle speed."
                },
                "degrees": {
                    "type": "number",
                    "minimum": 1.0,
                    "maximum": 360.0,
                    "default": 90.0,
                    "description": "Approximate angular rotation degrees to turn."
                },
                "duration_seconds": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 10.0,
                    "default": 0.6,
                    "description": "Optional rotation duration in seconds."
                }
            }
        }
    },
    {
        "name": "stop_rover",
        "description": "Immediately stop all motor motion and hold position.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "scan_surroundings",
        "description": "Perform an in-place rotation to scan and audit the visual environment.",
        "parameters": {
            "type": "object",
            "properties": {
                "degrees": {
                    "type": "number",
                    "minimum": 45.0,
                    "maximum": 360.0,
                    "default": 360.0,
                    "description": "Rotation sweep arc in degrees."
                },
                "speed": {
                    "type": "number",
                    "default": 0.30,
                    "description": "Slow scanning rotation speed."
                }
            }
        }
    },
    {
        "name": "capture_evidence",
        "description": "Capture a high-resolution camera snapshot and record a timestamped surveillance event.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Reason for evidence capture (e.g. 'unauthorized person detected', 'scheduled waypoint audit')."
                },
                "severity": {
                    "type": "string",
                    "enum": ["INFO", "WARNING", "CRITICAL"],
                    "default": "INFO",
                    "description": "Audit severity classification."
                }
            },
            "required": ["reason"]
        }
    },
    {
        "name": "get_rover_telemetry",
        "description": "Retrieve current battery, obstacle distance, camera detections, and location/motion state.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "send_telegram_alert",
        "description": "Dispatch a priority alert message with snapshot to Telegram security channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Notification body describing the detected event."
                },
                "attach_photo": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to attach the latest camera frame."
                }
            },
            "required": ["message"]
        }
    }
]


# ==============================================================================
# TOOL REGISTRY IMPLEMENTATION
# ==============================================================================

class ToolRegistry:
    """
    Central repository for strictly typed tools callable by Needle SLM & Groq Cloud LLM.
    Supports dynamic registration, parameter validation, schema export, and execution telemetry.
    """

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._execution_history: List[ToolExecutionResult] = []
        self._load_default_schemas()

    def _load_default_schemas(self) -> None:
        """Registers the canonical PRD tools with sensible default mock handlers."""
        for schema in ROVER_TOOLS_SCHEMAS:
            name = schema["name"]
            self._tools[name] = {
                "name": name,
                "description": schema["description"],
                "parameters": schema["parameters"],
                "handler": self._create_default_mock_handler(name),
            }

    def _create_default_mock_handler(self, name: str) -> Callable[..., Any]:
        """Provides a safe default handler when real hardware is not directly wired."""
        def default_mock(**kwargs):
            return {
                "status": "mock_executed",
                "tool": name,
                "parameters": kwargs,
                "message": f"Tool '{name}' executed successfully (simulator mode).",
            }
        return default_mock

    def register_tool(
        self,
        name: str,
        handler: Callable[..., Any],
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Registers or overrides an executable tool handler."""
        if name in self._tools and (description is None or parameters is None):
            # Preserve existing schema if not provided
            existing = self._tools[name]
            self._tools[name] = {
                "name": name,
                "description": description or existing["description"],
                "parameters": parameters or existing["parameters"],
                "handler": handler,
            }
        else:
            self._tools[name] = {
                "name": name,
                "description": description or f"Execute {name}",
                "parameters": parameters or {"type": "object", "properties": {}},
                "handler": handler,
            }
        logger.info("Registered tool: %s", name)

    def bind_rover_hardware(
        self,
        move_forward_fn: Optional[Callable] = None,
        move_backward_fn: Optional[Callable] = None,
        turn_left_fn: Optional[Callable] = None,
        turn_right_fn: Optional[Callable] = None,
        stop_rover_fn: Optional[Callable] = None,
        capture_evidence_fn: Optional[Callable] = None,
        get_telemetry_fn: Optional[Callable] = None,
        send_alert_fn: Optional[Callable] = None,
    ) -> None:
        """Convenience helper to bind actual rover control functions."""
        if move_forward_fn:
            self.register_tool("move_forward", move_forward_fn)
        if move_backward_fn:
            self.register_tool("move_backward", move_backward_fn)
        if turn_left_fn:
            self.register_tool("turn_left", turn_left_fn)
        if turn_right_fn:
            self.register_tool("turn_right", turn_right_fn)
        if stop_rover_fn:
            self.register_tool("stop_rover", stop_rover_fn)
        if capture_evidence_fn:
            self.register_tool("capture_evidence", capture_evidence_fn)
        if get_telemetry_fn:
            self.register_tool("get_rover_telemetry", get_telemetry_fn)
        if send_alert_fn:
            self.register_tool("send_telegram_alert", send_alert_fn)

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Returns standard OpenAPI/JSON Schema tool descriptors."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in self._tools.values()
        ]

    def get_openai_tool_specs(self) -> List[Dict[str, Any]]:
        """Formats tools for OpenAI / Groq tool_calls API format."""
        specs = []
        for t in self._tools.values():
            specs.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
            })
        return specs

    def validate_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validates arguments against the tool schema (types and required fields)."""
        tool = self.get_tool(tool_name)
        if not tool:
            return False, f"Unknown tool: '{tool_name}'"

        schema = tool["parameters"]
        required_fields = schema.get("required", [])
        for field_name in required_fields:
            if field_name not in arguments:
                return False, f"Missing required parameter '{field_name}' for tool '{tool_name}'"

        properties = schema.get("properties", {})
        for param, val in list(arguments.items()):
            if param in properties:
                prop_spec = properties[param]
                expected_type = prop_spec.get("type")

                # Auto-normalize percentage speed inputs (e.g. 40.0 -> 0.40)
                if "speed" in param.lower() and isinstance(val, (int, float)) and val > 1.0:
                    val = min(round(val / 100.0, 2), 1.0)
                    arguments[param] = val

                if expected_type == "number" and not isinstance(val, (int, float)):
                    return False, f"Parameter '{param}' must be a number, got {type(val).__name__}"
                elif expected_type == "string" and not isinstance(val, str):
                    return False, f"Parameter '{param}' must be a string, got {type(val).__name__}"
                elif expected_type == "boolean" and not isinstance(val, bool):
                    return False, f"Parameter '{param}' must be a boolean, got {type(val).__name__}"

                # Min/max bounds checks for numbers
                if isinstance(val, (int, float)):
                    if "minimum" in prop_spec and val < prop_spec["minimum"]:
                        return False, f"Parameter '{param}' ({val}) below minimum {prop_spec['minimum']}"
                    if "maximum" in prop_spec and val > prop_spec["maximum"]:
                        return False, f"Parameter '{param}' ({val}) exceeds maximum {prop_spec['maximum']}"

        return True, None

    def execute(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> ToolExecutionResult:
        """Executes a registered tool with error handling, telemetry, and timing."""
        arguments = arguments or {}
        start_time = time.perf_counter()

        tool = self.get_tool(tool_name)
        if not tool:
            res = ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                arguments=arguments,
                error=f"Tool '{tool_name}' not registered in Tool Registry.",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
            self._execution_history.append(res)
            return res

        valid, error_msg = self.validate_arguments(tool_name, arguments)
        if not valid:
            res = ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                arguments=arguments,
                error=error_msg,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
            self._execution_history.append(res)
            return res

        handler = tool["handler"]
        try:
            # Inject arguments that the handler actually accepts
            sig = inspect.signature(handler)
            accepted_params = sig.parameters
            filtered_args = {}
            for k, v in arguments.items():
                if k in accepted_params:
                    filtered_args[k] = v

            output = handler(**filtered_args)
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            res = ToolExecutionResult(
                success=True,
                tool_name=tool_name,
                arguments=arguments,
                output=output,
                execution_time_ms=execution_time_ms,
            )
        except Exception as e:
            logger.error("Error executing tool %s: %s", tool_name, e, exc_info=True)
            res = ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                arguments=arguments,
                error=str(e),
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        self._execution_history.append(res)
        return res

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._execution_history[-limit:]]


# Global shared instance
tool_registry = ToolRegistry()


# ==============================================================================
# CANONICAL CALLABLE FUNCTIONS (For direct use with needle.Needle(tools=[...]))
# Decorated with @needle.tool for native Cactus Compute Needle tool dispatch
# ==============================================================================

try:
    import needle
    needle_tool = needle.tool
except Exception:
    def needle_tool(fn):
        return fn


@needle_tool
def move_forward(speed: float = 0.35, duration_seconds: float = 1.0) -> Dict[str, Any]:
    """Drive rover forward for a specific duration or until stopped.

    Args:
        speed: Motor throttle speed fraction between 0.1 and 1.0 (or percentage 10-100).
        duration_seconds: Drive duration in seconds before halting.
    """
    if speed > 1.0:
        speed = min(round(speed / 100.0, 2), 1.0)
    return tool_registry.execute("move_forward", {"speed": speed, "duration_seconds": duration_seconds}).to_dict()


@needle_tool
def move_backward(speed: float = 0.30, duration_seconds: float = 1.0) -> Dict[str, Any]:
    """Drive rover in reverse for a specific duration.

    Args:
        speed: Motor reverse throttle speed fraction between 0.1 and 1.0 (or percentage 10-100).
        duration_seconds: Reverse drive duration in seconds before halting.
    """
    if speed > 1.0:
        speed = min(round(speed / 100.0, 2), 1.0)
    return tool_registry.execute("move_backward", {"speed": speed, "duration_seconds": duration_seconds}).to_dict()


@needle_tool
def turn_left(speed: float = 0.35, degrees: float = 90.0, duration_seconds: float = 0.6) -> Dict[str, Any]:
    """Pivot or spin rover counter-clockwise to the left.

    Args:
        speed: Turn throttle speed.
        degrees: Approximate angular rotation degrees to turn.
        duration_seconds: Rotation duration in seconds.
    """
    if speed > 1.0:
        speed = min(round(speed / 100.0, 2), 1.0)
    return tool_registry.execute("turn_left", {"speed": speed, "degrees": degrees, "duration_seconds": duration_seconds}).to_dict()


@needle_tool
def turn_right(speed: float = 0.35, degrees: float = 90.0, duration_seconds: float = 0.6) -> Dict[str, Any]:
    """Pivot or spin rover clockwise to the right.

    Args:
        speed: Turn throttle speed.
        degrees: Approximate angular rotation degrees to turn.
        duration_seconds: Rotation duration in seconds.
    """
    if speed > 1.0:
        speed = min(round(speed / 100.0, 2), 1.0)
    return tool_registry.execute("turn_right", {"speed": speed, "degrees": degrees, "duration_seconds": duration_seconds}).to_dict()


@needle_tool
def stop_rover() -> Dict[str, Any]:
    """Immediately stop all motor motion and hold position."""
    return tool_registry.execute("stop_rover", {}).to_dict()


@needle_tool
def scan_surroundings(degrees: float = 360.0, speed: float = 0.30) -> Dict[str, Any]:
    """Perform an in-place rotation to scan and audit the visual environment.

    Args:
        degrees: Rotation sweep arc in degrees.
        speed: Slow scanning rotation speed.
    """
    if speed > 1.0:
        speed = min(round(speed / 100.0, 2), 1.0)
    return tool_registry.execute("scan_surroundings", {"degrees": degrees, "speed": speed}).to_dict()


@needle_tool
def capture_evidence(reason: str, severity: str = "INFO") -> Dict[str, Any]:
    """Capture a high-resolution camera snapshot and record a timestamped surveillance event.

    Args:
        reason: Reason for evidence capture.
        severity: Audit severity classification ('INFO', 'WARNING', 'CRITICAL').
    """
    return tool_registry.execute("capture_evidence", {"reason": reason, "severity": severity}).to_dict()


@needle_tool
def get_rover_telemetry() -> Dict[str, Any]:
    """Retrieve current battery, obstacle distance, camera detections, and location/motion state."""
    return tool_registry.execute("get_rover_telemetry", {}).to_dict()


@needle_tool
def send_telegram_alert(message: str, attach_photo: bool = True) -> Dict[str, Any]:
    """Dispatch a priority alert message with snapshot to Telegram security channel.

    Args:
        message: Notification body describing the detected event.
        attach_photo: Whether to attach the latest camera frame.
    """
    return tool_registry.execute("send_telegram_alert", {"message": message, "attach_photo": attach_photo}).to_dict()


CANONICAL_TOOL_FUNCTIONS = [
    move_forward,
    move_backward,
    turn_left,
    turn_right,
    stop_rover,
    scan_surroundings,
    capture_evidence,
    get_rover_telemetry,
    send_telegram_alert,
]

