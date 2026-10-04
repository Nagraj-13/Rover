"""
EdgeRover — 4-Tier Hybrid Intelligence Stack (PRD Section 4).

Tiers:
- Tier 1: Groq Cloud Reasoning (llama-3.3-70b-versatile)
- Tier 2: Needle 2 Edge Tool Calling (Local SLM Router)
- Tier 3: Laya System-1 Typed Decision Evaluator (World State Triage & Avoidance)
- Tier 4: Ultralytics YOLO Real-Time Perception (vision package)
"""

from intelligence.tools import (
    ROVER_TOOLS_SCHEMAS,
    ToolExecutionResult,
    ToolRegistry,
    tool_registry,
)
from intelligence.needle import (
    NeedleCommandResult,
    NeedleRouter,
    needle_router,
)
from intelligence.laya import (
    AvoidanceDirection,
    EventSeverity,
    LayaDecisionEngine,
    NavigationDecision,
    RecommendedAction,
    TriageDecision,
    WorldState,
    laya_engine,
)
from intelligence.groq_client import (
    DebriefReport,
    GroqBrain,
    MissionSpec,
    MissionStep,
    groq_brain,
)

__all__ = [
    # Tier 1
    "GroqBrain",
    "groq_brain",
    "MissionSpec",
    "MissionStep",
    "DebriefReport",
    # Tier 2
    "NeedleRouter",
    "needle_router",
    "NeedleCommandResult",
    # Tier 3
    "LayaDecisionEngine",
    "laya_engine",
    "WorldState",
    "TriageDecision",
    "NavigationDecision",
    "EventSeverity",
    "RecommendedAction",
    "AvoidanceDirection",
    # Tool Registry
    "ToolRegistry",
    "tool_registry",
    "ToolExecutionResult",
    "ROVER_TOOLS_SCHEMAS",
]
