from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class ModelRegistry:
    aliases: dict[str, str] = field(default_factory=dict)

    def resolve(self, alias: str) -> str:
        return self.aliases.get(alias, alias)

    def refresh_openai_compatible(self, base_url: str, provider: str, api_key: str) -> None:
        models_url = base_url.rstrip("/")
        if models_url.endswith("/chat/completions"):
            models_url = models_url[: -len("/chat/completions")] + "/models"
        request = urllib.request.Request(
            models_url,
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return
        ids = _extract_model_ids(payload)
        self._map_aliases(provider, ids)

    def _map_aliases(self, provider: str, ids: list[str]) -> None:
        if provider == "notion" and ids:
            self.aliases["notion-opus-latest"] = ids[0]
        for model_id in ids:
            lowered = model_id.lower()
            if "claude" in lowered and "opus" in lowered:
                self.aliases.setdefault("claude-opus-thinking-latest", model_id)
            if "gpt" in lowered:
                self.aliases.setdefault("gpt-premium-latest", model_id)
            if "gemini" in lowered and "flash" in lowered:
                self.aliases.setdefault("gemini-flash-medium-latest", model_id)
            if "swe" in lowered:
                self.aliases.setdefault("swe-fast-latest", model_id)


def _extract_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(str(item["id"]))
    return ids
