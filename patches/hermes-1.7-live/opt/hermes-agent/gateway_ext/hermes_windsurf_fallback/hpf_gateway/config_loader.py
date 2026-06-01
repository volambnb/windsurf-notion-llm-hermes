from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TierConfig:
    tier: int
    name: str
    provider: str
    endpoint: str
    model_aliases: list[str]
    max_retries_per_model: int
    advisor_allowed: bool
    requires_tool_calling: bool
    enabled: bool = True


@dataclass(frozen=True)
class AdvisorConfig:
    provider: str
    endpoint: str
    model_aliases: list[str]
    trigger_score: float
    max_calls_per_task: int
    confidence_min: float


@dataclass(frozen=True)
class FallbackConfig:
    tiers: list[TierConfig]
    advisor: AdvisorConfig
    timeout_seconds: int
    http_status_triggers: set[int]
    error_keywords: tuple[str, ...]


@dataclass(frozen=True)
class PlanFirstConfig:
    policy: str
    provider: str
    endpoint: str
    model_alias: str
    output_dir: Path
    max_retries: int
    required_headings: tuple[str, ...]


def default_fallback_config() -> FallbackConfig:
    windsurf = "http://127.0.0.1:3003/v1/chat/completions"
    notion = "http://127.0.0.1:4200/v1/chat/completions"
    tiers = [
        TierConfig(1, "Windsurf Premium", "windsurf", windsurf, ["claude-opus-4.6-thinking", "claude-opus-4-7-high-thinking", "gpt-5.5"], 2, False, True),
        TierConfig(2, "Windsurf Frontier Free", "windsurf", windsurf, ["gemini-3.0-flash-high", "gemini-2.5-flash"], 2, True, True),
        TierConfig(3, "Windsurf SWE", "windsurf", windsurf, ["swe-1.6-fast", "swe-1.6"], 2, True, True),
        TierConfig(4, "Notion Advisor and Log Analysis", "notion", notion, ["claude-opus4.7"], 1, True, False),
    ]
    advisor = AdvisorConfig(
        provider="notion",
        endpoint=notion,
        model_aliases=["claude-opus4.7"],
        trigger_score=0.70,
        max_calls_per_task=2,
        confidence_min=0.60,
    )
    return FallbackConfig(
        tiers=tiers,
        advisor=advisor,
        timeout_seconds=60,
        http_status_triggers={402, 429, 503, 504},
        error_keywords=("quota", "rate limit", "trial limit", "credit exhausted", "account suspended", "model overloaded", "model_not_found"),
    )


def default_plan_first_config() -> PlanFirstConfig:
    output_dir = Path(os.environ.get("HERMES_PLANS_DIR", "~/.hermes/plans")).expanduser()
    return PlanFirstConfig(
        policy=os.environ.get("HERMES_PLAN_POLICY", "balanced"),
        provider="notion",
        endpoint="http://127.0.0.1:4200/v1/chat/completions",
        model_alias="claude-opus4.7",
        output_dir=output_dir,
        max_retries=2,
        required_headings=("# ", "## Goal", "## Context", "## Tasks", "## Tool Plan", "## Acceptance Criteria", "## Risks"),
    )


def load_yaml_dict(path: Path) -> dict[str, object]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {}
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def load_fallback_config(path: Path) -> FallbackConfig:
    data = load_yaml_dict(path)
    if not data:
        return default_fallback_config()
    coding_lane = data.get("coding_lane")
    advisor_data = data.get("advisor")
    if not isinstance(coding_lane, dict) or not isinstance(advisor_data, dict):
        return default_fallback_config()
    raw_tiers = coding_lane.get("tiers")
    tiers: list[TierConfig] = []
    if isinstance(raw_tiers, list):
        for item in raw_tiers:
            if isinstance(item, dict) and item.get("enabled", True):
                tiers.append(_tier_from_dict(item))
    if not tiers:
        return default_fallback_config()
    advisor = AdvisorConfig(
        provider=str(advisor_data.get("provider", "notion")),
        endpoint=str(advisor_data.get("endpoint", "http://127.0.0.1:4200/v1/chat/completions")),
        model_aliases=_str_list(advisor_data.get("model_aliases"), ["claude-opus4.7"]),
        trigger_score=0.70,
        max_calls_per_task=int(advisor_data.get("max_calls_per_task", 2)),
        confidence_min=float(advisor_data.get("confidence_min", 0.60)),
    )
    triggers = data.get("fallback_triggers")
    timeout = 60
    statuses = {402, 429, 503, 504}
    keywords = default_fallback_config().error_keywords
    if isinstance(triggers, dict):
        timeout = int(triggers.get("timeout_seconds", timeout))
        statuses = {int(value) for value in _str_list(triggers.get("http_status"), ["402", "429", "503", "504"])}
        keywords = tuple(_str_list(triggers.get("error_keywords"), list(keywords)))
    return FallbackConfig(tiers, advisor, timeout, statuses, keywords)


def _tier_from_dict(item: dict[str, object]) -> TierConfig:
    return TierConfig(
        tier=int(item.get("tier", 0)),
        name=str(item.get("name", "Unnamed Tier")),
        provider=str(item.get("provider", "")),
        endpoint=str(item.get("endpoint", "")),
        model_aliases=_str_list(item.get("model_aliases"), []),
        max_retries_per_model=int(item.get("max_retries_per_model", 1)),
        advisor_allowed=bool(item.get("advisor_allowed", False)),
        requires_tool_calling=bool(item.get("requires_tool_calling", False)),
        enabled=bool(item.get("enabled", True)),
    )


def _str_list(value: object, default: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return default
