from __future__ import annotations

import os

from .types import Intent, RouteDecision


CODING_KEYWORDS = (
    "code",
    "repo",
    "file",
    "bug",
    "fix",
    "implement",
    "refactor",
    "test",
    "deploy",
    "script",
    "config",
    "folder",
    "project",
)


def classify_intent(message: str) -> tuple[Intent, float]:
    text = message.lower().strip()
    if not text:
        return "chat", 0.9
    if text.startswith("!nopl"):
        return "trivial", 0.95
    hits = sum(1 for keyword in CODING_KEYWORDS if keyword in text)
    if hits >= 2 or len(text.split()) > 50:
        return "project", 0.8
    if hits == 1:
        return "coding", 0.75
    if len(text.split()) <= 12:
        return "chat", 0.75
    return "project", 0.55


def route_decision(message: str, policy: str = "balanced") -> RouteDecision:
    intent, confidence = classify_intent(message)
    if message.strip().startswith("!nopl"):
        return RouteDecision(intent, confidence, False, "user override")
    env_required = os.environ.get("HERMES_PLAN_REQUIRED", "").lower()
    if env_required in {"0", "false", "no"}:
        return RouteDecision(intent, confidence, False, "env override")
    if policy == "strict":
        needs_plan = intent in {"project", "coding", "trivial"}
    elif policy == "manual":
        needs_plan = message.strip().startswith("!plan")
    else:
        needs_plan = intent in {"project", "coding"} and len(message.split()) > 6
    return RouteDecision(intent, confidence, needs_plan, f"policy={policy}")
