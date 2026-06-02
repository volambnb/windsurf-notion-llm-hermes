"""Self-healing helpers for Hermes /code runs pinned to Windsurf.

This module is intentionally side-effect light. Runtime hooks call
``record_event`` to persist classified failures, and deployment scripts may call
``restart_windsurf_clean`` or ``normalize_windsurf_channels`` for explicit
maintenance. The router never changes provider/model by itself.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


HERMES_HOME = Path(os.getenv("HERMES_HOME", "/root/.hermes"))
EVENT_DIR = HERMES_HOME / "self_heal"
EVENT_LOG = EVENT_DIR / "events.jsonl"
ACTIVE_PLAN_FILE = HERMES_HOME / "active_code_plan.json"
SANE_POSIX_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass
class RecoveryDecision:
    error_type: str
    actions: list[str]
    retry_same_model: bool
    resume_from_checkpoint: bool
    diagnostic: str
    project_folder: str | None = None
    session_id: str | None = None


def classify_error(text: str | dict[str, Any] | None) -> str:
    """Classify model/provider/tool failures from logs or event payloads."""
    if isinstance(text, dict):
        explicit_type = str(text.get("type") or "")
        if explicit_type in {
            "stream_stall",
            "tool_call_malformed",
            "terminal_path_broken",
            "provider_timeout",
            "account_rate_limit",
            "csrf_auth",
            "context_bloat",
            "repeat_tool_loop",
        }:
            return explicit_type
        raw = json.dumps(text, ensure_ascii=False)
    else:
        raw = str(text or "")
    s = raw.lower()
    if "invalid csrf token" in s or "grpc unauthenticated" in s:
        return "csrf_auth"
    if "rate limit" in s or "free trial plan" in s or "exhausted" in s:
        return "account_rate_limit"
    if "context deadline exceeded" in s or "client.timeout" in s or "reading body" in s:
        return "provider_timeout"
    if "partial stream dropped tool call" in s or "stream stalled mid tool-call" in s:
        return "stream_stall"
    if "expected string, got nonetype" in s or "command value: nonetype" in s:
        return "tool_call_malformed"
    if "command not found" in s and any(cmd in s for cmd in ("ls:", "which:", "head:")):
        return "terminal_path_broken"
    if "same_tool_failure_warning" in s or "repeated_exact_failure_warning" in s:
        return "repeat_tool_loop"
    if re.search(r"\bturns=\d{2,}\b", s) or re.search(r"\bchars=(2\d{5,}|3\d{5,}|[4-9]\d{5,})\b", s):
        return "context_bloat"
    return "unknown"


def active_project(session_id: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Return ``(session_id, project_folder, plan_state)`` for the active /code run."""
    try:
        data = json.loads(ACTIVE_PLAN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return session_id, None, None
    key = session_id or "current"
    item = data.get(key) if isinstance(data, dict) else None
    if not item and isinstance(data, dict):
        item = data.get("current")
    if not isinstance(item, dict):
        return session_id, None, None
    return (
        str(item.get("session_id") or session_id or ""),
        str(item.get("project_folder") or "") or None,
        str(item.get("active_plan_state") or "") or None,
    )


def checkpoint_path(project_folder: str | None) -> Path | None:
    if not project_folder:
        return None
    return Path(project_folder) / ".hermes-code-state.json"


def load_checkpoint(project_folder: str | None) -> dict[str, Any]:
    path = checkpoint_path(project_folder)
    if not path or not path.exists():
        return {
            "current_task": None,
            "successful_tools": [],
            "successful_commands": [],
            "created_or_changed_files": [],
            "last_stable_point": None,
            "updated_at": None,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_checkpoint(project_folder: str | None, updates: dict[str, Any]) -> dict[str, Any]:
    path = checkpoint_path(project_folder)
    if not path:
        return {}
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_checkpoint(project_folder)
    data.update(updates)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def build_resume_prompt(project_folder: str | None, error_type: str, reason: str = "") -> str:
    cp = load_checkpoint(project_folder)
    plan = str(Path(project_folder or "") / "PLAN.md") if project_folder else "Current Plan File"
    state = str(Path(project_folder or "") / "PLAN.state.json") if project_folder else "Current Plan State"
    checkpoint = str(checkpoint_path(project_folder) or ".hermes-code-state.json")
    return (
        "Self-heal resume from checkpoint.\n"
        f"Error Type: {error_type}\n"
        f"Reason: {reason[:500]}\n"
        f"Project Folder: {project_folder or ''}\n"
        f"Current Plan File: {plan}\n"
        f"Current Plan State: {state}\n"
        f"Checkpoint File: {checkpoint}\n"
        f"Current Task: {cp.get('current_task') or 'next unfinished task'}\n"
        "Rules:\n"
        "- Continue with the same provider/model: windsurf/deepseek-v4-pro.\n"
        "- Do not use /retry semantics; do not replay already successful commands.\n"
        "- Read only PLAN.md, PLAN.state.json, checkpoint, and files needed for the next unfinished task.\n"
        "- If a terminal command needs PATH, keep /usr/bin:/bin available.\n"
        "- If a tool call failed because arguments were null/object, retry with a valid string argument.\n"
        "- If context is too large, summarize local repo inspection into checkpoint before continuing.\n"
    )


def decide_recovery(
    error: str | dict[str, Any],
    session_id: str | None = None,
    project_folder: str | None = None,
) -> RecoveryDecision:
    error_type = classify_error(error)
    sid, active_folder, _state = active_project(session_id)
    folder = project_folder or active_folder
    actions: list[str] = []
    retry_same = False
    resume = False
    diagnostic = "No automatic recovery rule matched."

    if error_type in {"stream_stall", "provider_timeout"}:
        actions = ["compress_context", "resume_from_checkpoint", "retry_same_model"]
        retry_same = True
        resume = True
        diagnostic = "Transient Windsurf stream/provider failure; retry same model from checkpoint."
    elif error_type == "tool_call_malformed":
        actions = ["resume_from_checkpoint", "retry_same_model"]
        retry_same = True
        resume = True
        diagnostic = "Model emitted malformed tool arguments; retry same model with valid string tool args."
    elif error_type == "terminal_path_broken":
        actions = ["normalize_terminal_path", "resume_from_checkpoint", "retry_same_model"]
        retry_same = True
        resume = True
        diagnostic = "Terminal PATH was overwritten; restore sane PATH and resume."
    elif error_type == "repeat_tool_loop":
        actions = ["stop_repeated_tool", "resume_from_checkpoint"]
        resume = True
        diagnostic = "Repeated identical tool failure; resume with cached result or next step."
    elif error_type == "account_rate_limit":
        actions = ["cooldown_account", "retry_same_model"]
        retry_same = True
        diagnostic = "Windsurf account rate-limited; rotate/cooldown account but keep same model."
    elif error_type == "csrf_auth":
        actions = ["restart_windsurf_clean", "retry_same_model"]
        retry_same = True
        diagnostic = "Windsurf language-server auth stale; clean restart and retry same model."
    elif error_type == "context_bloat":
        actions = ["compress_context", "resume_from_checkpoint", "retry_same_model"]
        retry_same = True
        resume = True
        diagnostic = "Context is too large; compress and resume from checkpoint."

    return RecoveryDecision(error_type, actions, retry_same, resume, diagnostic, folder, sid)


def record_event(event: str | dict[str, Any], **extra: Any) -> RecoveryDecision:
    """Classify and append a recovery event to ``~/.hermes/self_heal/events.jsonl``."""
    decision = decide_recovery(event, extra.get("session_id"), extra.get("project_folder"))
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event if isinstance(event, dict) else {"message": str(event)[:2000]},
        "extra": extra,
        "decision": asdict(decision),
    }
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    if decision.project_folder and decision.resume_from_checkpoint:
        save_checkpoint(
            decision.project_folder,
            {
                "last_error_type": decision.error_type,
                "last_recovery_actions": decision.actions,
                "last_resume_prompt": build_resume_prompt(
                    decision.project_folder,
                    decision.error_type,
                    str(event),
                ),
            },
        )
    return decision


def normalize_path_exports(command: str) -> str:
    """Append sane POSIX PATH to model-written PATH exports that hide /usr/bin."""
    if "export PATH=" not in command:
        return command
    out: list[str] = []
    for line in command.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("export PATH=") and "/usr/bin" not in stripped:
            line = f"{line}:${{PATH:-{SANE_POSIX_PATH}}}:{SANE_POSIX_PATH}"
            record_event({"type": "terminal_path_broken", "line": stripped[:200]})
        out.append(line)
    return "\n".join(out)


def restart_windsurf_clean() -> int:
    """Restart WindsurfAPI and kill stale language-server processes."""
    cmds = [
        ["systemctl", "stop", "windsurf-api.service"],
        ["pkill", "-f", "language_server_linux_x64"],
        ["pkill", "-f", "windsurf-api"],
        ["systemctl", "start", "windsurf-api.service"],
    ]
    rc = 0
    for cmd in cmds:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rc = rc or proc.returncode
        if cmd[0] == "systemctl" and cmd[1] == "start":
            time.sleep(8)
    record_event({"type": "csrf_auth", "message": "restart_windsurf_clean", "rc": rc})
    return rc


def normalize_windsurf_channels(
    accounts_path: str = "/opt/WindsurfAPI/accounts.json",
    channels_path: str = "/root/.local/share/windsurf-api/channels.json",
) -> int:
    """Convert account-pool records into WindsurfAPI channel runtime schema."""
    src = Path(accounts_path)
    dst = Path(channels_path)
    if not src.exists():
        return 1
    try:
        accounts = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return 1
    if not isinstance(accounts, list):
        return 1
    if dst.exists():
        shutil.copy2(dst, dst.with_name(dst.name + f".bak.selfheal-{int(time.time())}"))
    now = int(time.time() * 1000)
    channels = []
    for i, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue
        ch = dict(account)
        ch.setdefault("id", f"acc{i+1:02d}")
        ch.setdefault("email", f"account-{i+1}")
        ch.setdefault("tier", "pro")
        ch["status"] = "active"
        ch["errorCount"] = 0
        ch["lastUsed"] = 0
        ch["rpmHistory"] = []
        ch.setdefault("createdAt", now)
        channels.append(ch)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(channels, indent=2, ensure_ascii=False), encoding="utf-8")
    record_event({"type": "account_rate_limit", "message": "normalize_windsurf_channels", "count": len(channels)})
    return 0


def self_test() -> dict[str, Any]:
    samples = {
        "provider_timeout": "context deadline exceeded (Client.Timeout while reading body)",
        "tool_call_malformed": "Invalid command: expected string, got NoneType",
        "terminal_path_broken": "/usr/bin/bash: line 3: ls: command not found",
        "csrf_auth": "invalid CSRF token (gRPC UNAUTHENTICATED)",
        "account_rate_limit": "Reached overall message rate limit for your free trial plan",
        "stream_stall": "Partial stream dropped tool call(s) ['terminal'] after 114 chars",
    }
    return {name: asdict(decide_recovery(text)) for name, text in samples.items()}
