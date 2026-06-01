from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .advisor import call_notion_advisor
from .config_loader import FallbackConfig, TierConfig
from .model_registry import ModelRegistry
from .provider_client import ProviderClient
from .stuck_detector import StuckDetector, classify_error, error_fingerprint
from .types import AdvisorPatch, FallbackEvent, ProviderError, ProviderResponse, RequestBudget, TaskState


class AllTiersExhaustedError(RuntimeError):
    pass


class FallbackRouter:
    def __init__(
        self,
        config: FallbackConfig,
        client: ProviderClient,
        model_registry: ModelRegistry | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.model_registry = model_registry or ModelRegistry()
        self.log_dir = log_dir or Path("~/.hermes/logs").expanduser()
        self.detector = StuckDetector()

    def call_with_fallback(
        self,
        request: dict[str, object],
        session_id: str,
        task_summary: str,
        dry_run: bool = False,
    ) -> ProviderResponse | dict[str, object]:
        budget = RequestBudget(max_advisor_calls_per_task=self.config.advisor.max_calls_per_task)
        last_error = ""
        for tier in self.config.tiers:
            if not budget.can_switch_tier() and tier.tier > 1:
                break
            result = self._try_tier(tier, request, session_id, task_summary, budget, dry_run)
            if isinstance(result, ProviderResponse) or dry_run:
                return result
            last_error = result
            if tier.advisor_allowed and "unknown" in result:
                patch = self._maybe_call_advisor(tier, session_id, task_summary, result, budget, dry_run)
                if patch and patch.valid:
                    return {"advisor_patch": patch.__dict__, "tier": tier.tier}
            budget.tier_switches += 1
        raise AllTiersExhaustedError(last_error or "all tiers exhausted")

    def _try_tier(
        self,
        tier: TierConfig,
        request: dict[str, object],
        session_id: str,
        task_summary: str,
        budget: RequestBudget,
        dry_run: bool,
    ) -> ProviderResponse | str | dict[str, object]:
        messages = _messages_from_request(request)
        for alias in tier.model_aliases:
            model = self.model_registry.resolve(alias)
            for retry in range(tier.max_retries_per_model):
                if dry_run:
                    return {"route": {"tier": tier.tier, "provider": tier.provider, "model": model, "retry": retry}}
                if not budget.can_call_llm():
                    return "budget_exhausted"
                budget.llm_calls += 1
                try:
                    return self.client.chat_completion(tier.provider, tier.endpoint, model, messages)
                except ProviderError as exc:
                    reason = classify_error(exc.status_code, exc.message)
                    self._log_event(FallbackEvent(session_id, tier.tier, model, None, None, reason, exc.message, task_summary, retry, exc.status_code))
                    if reason in {"known_quota", "known_fatal"}:
                        break
                    if reason == "unknown":
                        return f"unknown:{exc.message}"
        return f"tier_{tier.tier}_exhausted"

    def _maybe_call_advisor(
        self,
        tier: TierConfig,
        session_id: str,
        task_summary: str,
        error_message: str,
        budget: RequestBudget,
        dry_run: bool,
    ) -> AdvisorPatch | None:
        task_state = TaskState(
            session_id=session_id,
            task_id="fallback",
            current_tier=tier.tier,
            task_goal=task_summary,
            stderr=error_message,
            fingerprint_current=error_fingerprint(error_message),
            attempts=3,
            elapsed_minutes=5.0,
        )
        score = self.detector.compute_score(task_state)
        if score < self.config.advisor.trigger_score or not budget.can_call_advisor():
            return None
        budget.advisor_calls += 1
        if dry_run:
            return AdvisorPatch("other", "dry-run", "skip", [], False, 0.0)
        return call_notion_advisor(task_state, self.config.advisor, self.client)

    def _log_event(self, event: FallbackEvent) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"fallback-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": event.session_id,
            "from_tier": event.from_tier,
            "from_model": event.from_model,
            "to_tier": event.to_tier,
            "to_model": event.to_model,
            "trigger": event.trigger,
            "http_status": event.http_status,
            "error_message": event.error_message,
            "task_summary": event.task_summary,
            "retry_count": event.retry_count,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _messages_from_request(request: dict[str, object]) -> list[dict[str, str]]:
    messages = request.get("messages")
    if isinstance(messages, list):
        parsed: list[dict[str, str]] = []
        for item in messages:
            if isinstance(item, dict):
                role = str(item.get("role", "user"))
                content = str(item.get("content", ""))
                parsed.append({"role": role, "content": content})
        return parsed
    prompt = str(request.get("prompt", ""))
    return [{"role": "user", "content": prompt}]
