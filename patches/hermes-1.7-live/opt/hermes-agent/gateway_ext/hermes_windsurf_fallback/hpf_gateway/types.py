from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Intent = Literal["project", "coding", "trivial", "chat"]
TaskStatus = Literal["done", "failed", "skipped"]
ErrorClass = Literal[
    "known_transient",
    "known_quota",
    "known_fatal",
    "unknown",
]


@dataclass(frozen=True)
class ProviderModel:
    provider: str
    endpoint: str
    model: str
    tier: int
    tier_name: str
    requires_tool_calling: bool = False


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    model: str
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True)
class ProviderError(Exception):
    provider: str
    model: str
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        suffix = f" ({self.status_code})" if self.status_code else ""
        return f"{self.provider}/{self.model}: {self.message}{suffix}"


@dataclass(frozen=True)
class AdvisorPatch:
    error_class: str
    root_cause: str
    fix_strategy: str
    tool_calls: list[dict[str, object]]
    retry_now: bool
    confidence: float

    @property
    def valid(self) -> bool:
        return self.confidence >= 0.60 and bool(self.tool_calls)


@dataclass
class TaskState:
    session_id: str
    task_id: str
    current_tier: int
    task_goal: str
    stderr: str = ""
    diff_current: str = ""
    diff_previous: str = ""
    fingerprint_current: str = ""
    fingerprint_previous: str = ""
    attempts: int = 0
    elapsed_minutes: float = 0.0
    progress_current: float = 0.0
    progress_previous: float = 0.0
    advisor_calls_count: int = 0


@dataclass(frozen=True)
class PlanResult:
    path: Path
    state_path: Path
    slug: str
    task_count: int
    used_fallback: bool


@dataclass
class RouteDecision:
    intent: Intent
    confidence: float
    needs_plan: bool
    reason: str


@dataclass
class FallbackEvent:
    session_id: str
    from_tier: int
    from_model: str
    to_tier: int | None
    to_model: str | None
    trigger: str
    error_message: str
    task_summary: str
    retry_count: int
    http_status: int | None = None


@dataclass
class RequestBudget:
    max_tier_switches_per_task: int = 4
    max_llm_calls_per_task: int = 16
    max_advisor_calls_per_task: int = 2
    tier_switches: int = 0
    llm_calls: int = 0
    advisor_calls: int = 0

    def can_call_llm(self) -> bool:
        return self.llm_calls < self.max_llm_calls_per_task

    def can_switch_tier(self) -> bool:
        return self.tier_switches < self.max_tier_switches_per_task

    def can_call_advisor(self) -> bool:
        return self.advisor_calls < self.max_advisor_calls_per_task


@dataclass(frozen=True)
class RuntimePaths:
    hermes_home: Path
    plans_dir: Path
    logs_dir: Path
    reports_dir: Path

    @staticmethod
    def from_home(home: Path) -> "RuntimePaths":
        return RuntimePaths(
            hermes_home=home,
            plans_dir=home / "plans",
            logs_dir=home / "logs",
            reports_dir=home / "reports",
        )


@dataclass
class PlanState:
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    task_status: dict[str, TaskStatus] = field(default_factory=dict)
    content_hash: str = ""
