from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .types import PlanState, TaskStatus


def plan_content_hash(plan_path: Path) -> str:
    content = plan_path.read_bytes()
    return hashlib.sha1(content).hexdigest()


def state_path_for_plan(plan_path: Path) -> Path:
    return plan_path.with_suffix(".state.json")


def load_state(plan_path: Path) -> PlanState:
    state_path = state_path_for_plan(plan_path)
    if not state_path.exists():
        return PlanState(content_hash=plan_content_hash(plan_path))
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    task_status = raw.get("task_status", {})
    return PlanState(
        completed_tasks=int(raw.get("completed_tasks", 0)),
        failed_tasks=int(raw.get("failed_tasks", 0)),
        skipped_tasks=int(raw.get("skipped_tasks", 0)),
        task_status={str(key): str(value) for key, value in task_status.items()},
        content_hash=str(raw.get("content_hash", "")),
    )


def tick_task(plan_path: Path, task_id: str, status: TaskStatus, note: str = "") -> PlanState:
    state = load_state(plan_path)
    state.task_status[task_id] = status
    counts = {"done": 0, "failed": 0, "skipped": 0}
    for value in state.task_status.values():
        counts[value] = counts.get(value, 0) + 1
    state.completed_tasks = counts["done"]
    state.failed_tasks = counts["failed"]
    state.skipped_tasks = counts["skipped"]
    state.content_hash = plan_content_hash(plan_path)
    payload: dict[str, object] = {
        "completed_tasks": state.completed_tasks,
        "failed_tasks": state.failed_tasks,
        "skipped_tasks": state.skipped_tasks,
        "task_status": state.task_status,
        "content_hash": state.content_hash,
    }
    if note:
        payload["last_note"] = note
    state_path_for_plan(plan_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def count_tasks(plan_text: str) -> int:
    return sum(1 for line in plan_text.splitlines() if line.strip().startswith("- [ ]"))
