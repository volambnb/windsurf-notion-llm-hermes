from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .types import ProviderError, ProviderResponse


class ProviderClient:
    def __init__(self, timeout_seconds: int = 60) -> None:
        self.timeout_seconds = timeout_seconds

    def chat_completion(
        self,
        provider: str,
        endpoint: str,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
    ) -> ProviderResponse:
        body: dict[str, object] = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key(provider)}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise ProviderError(provider, model, "non-object response", response.status)
                return ProviderResponse(provider, model, response.status, parsed)
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(provider, model, message, exc.code) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(provider, model, str(exc.reason), None) from exc
        except TimeoutError as exc:
            raise ProviderError(provider, model, "timeout", None) from exc

    def _api_key(self, provider: str) -> str:
        env_map = {
            "windsurf": "WINDSURF_API_KEY",
            "notion": "NOTION_PROXY_API_KEY",
            "openai_direct": "OPENAI_API_KEY",
        }
        return os.environ.get(env_map.get(provider, ""), "")


def extract_text(response: ProviderResponse) -> str:
    choices = response.body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""
