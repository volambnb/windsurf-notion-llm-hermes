from __future__ import annotations

import json
import re

from .config_loader import AdvisorConfig
from .provider_client import ProviderClient, extract_text
from .types import AdvisorPatch, TaskState


ADVISOR_SYSTEM_PROMPT = """You are Notion Opus acting as Hermes Advisor.
Return only JSON with this schema:
{
  "error_class": "rate|auth|payload|model_bug|context_overflow|tool_mismatch|other",
  "root_cause": "one sentence",
  "fix_strategy": "patch_request|patch_code|reduce_context|change_tools|wait_seconds|skip",
  "tool_calls": [{"tool": "edit_file|run_terminal", "path": "optional", "patch": "optional", "cmd": "optional"}],
  "retry_now": true,
  "confidence": 0.0
}
No markdown."""


def call_notion_advisor(
    task_state: TaskState,
    config: AdvisorConfig,
    client: ProviderClient,
) -> AdvisorPatch:
    context = compact_advisor_context(task_state)
    messages = [
        {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]
    response = client.chat_completion(config.provider, config.endpoint, config.model_aliases[0], messages)
    return parse_advisor_patch(extract_text(response))


def compact_advisor_context(task_state: TaskState) -> str:
    stderr = task_state.stderr[-2500:]
    diff = task_state.diff_current[-2500:]
    return (
        f"Task: {task_state.task_goal}\n"
        f"Tier: {task_state.current_tier}\n"
        f"Attempts: {task_state.attempts}\n"
        f"Fingerprint: {task_state.fingerprint_current}\n"
        f"stderr:\n{stderr}\n\n"
        f"last diff:\n{diff}\n"
    )


def parse_advisor_patch(text: str) -> AdvisorPatch:
    payload = _extract_json_object(text)
    data = json.loads(payload)
    tool_calls = data.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        tool_calls = []
    return AdvisorPatch(
        error_class=str(data.get("error_class", "other")),
        root_cause=str(data.get("root_cause", "")),
        fix_strategy=str(data.get("fix_strategy", "skip")),
        tool_calls=[item for item in tool_calls if isinstance(item, dict)],
        retry_now=bool(data.get("retry_now", False)),
        confidence=float(data.get("confidence", 0.0)),
    )


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    raise ValueError("advisor response did not contain JSON")
