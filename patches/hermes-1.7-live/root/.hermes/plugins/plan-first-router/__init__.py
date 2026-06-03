from __future__ import annotations

import json
import logging
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

EXT_ROOT = Path("/opt/hermes-agent/gateway_ext/hermes_windsurf_fallback")
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

MARKER = "[HERMES PLAN-FIRST ACTIVE]"
CODE_COMMAND = "/code"
PROJECTS_ROOT = Path(os.environ.get("HERMES_CODE_PROJECTS_ROOT", "/opt/hermes-agent/projects"))
ACTIVE_PLAN_FILE = Path(os.environ.get("HERMES_ACTIVE_CODE_PLAN_FILE", "/root/.hermes/active_code_plan.json"))
SANE_PATH = "/opt/hermes-agent/.venv/bin:/root/.hermes/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

SMART_TECHNICAL_POLICY = """/code technical planning policy (always apply):
1. Treat the implementer as a generic coding agent, not a Hermes-specific coding agent.
2. If the request contains GitHub repository URLs, treat those repositories as the source of truth for language, framework, package manager, folder layout, conventions, APIs, scripts, tests, deployment style, and compatibility. The plan must inspect/clone/read the repo before implementation.
3. Prefer the repository's existing ecosystem for maintainability. If the repo is Node/TypeScript, Python, Go, Rust, etc., keep that ecosystem unless there is a strong reason to diverge.
4. Only propose Go or Rust when the repo already uses them, the user explicitly asks for them, or there is a concrete reason such as performance, single-binary deployment, concurrency, memory safety, CLI/agent infrastructure, or low-resource VPS deployment.
5. If the request does not contain a GitHub URL and is only an idea or product description, first normalize it into a precise technical product brief: target users, core workflow, required screens/APIs/modules, data model, runtime constraints, deployment target, and non-goals.
6. For idea-only requests, search GitHub for mature, relevant repositories whose technical purpose, architecture, or product behavior is similar or adjacent. Use these repositories as reference material, not mandatory dependencies. Prefer actively maintained repos with clear README, package files, scripts, tests, and deploy docs.
7. For each selected reference repo, analyze stack, folder layout, core modules, important functions/classes, scripts, tests, build/deploy flow, strengths, weaknesses, and which ideas should or should not be reused.
8. Choose the most pragmatic stable stack after comparing the normalized product brief with the GitHub references. Use modern stable 2026 best practices and avoid beta/experimental dependencies unless they clearly reduce risk.
9. Keep the existing required markdown headings exactly: #, ## Goal, ## Context, ## Tasks, ## Tool Plan, ## Acceptance Criteria, ## Risks.
10. In Context, include normalized technical brief, repo/stack inference, GitHub reference repos inspected or to inspect, language-choice rationale, and why the final stack is appropriate.
11. In Tasks, use executable checklist IDs like **T1** and mention concrete files/modules/functions/scripts to create, inspect, or modify.
12. In Tool Plan, include exact commands/scripts, GitHub search terms, repo inspection order, clone/read commands, package-manager commands, build/test commands, and deploy-readiness checks.
13. In Acceptance Criteria, include local run success, test success, implementation completeness, UX/API behavior, and deploy-ready criteria.
14. In Risks, include dependency/version risk, GitHub reference mismatch risk, tool-calling/provider risk, repo compatibility risk, security/secrets risk, and VPS deployment risk.
"""


def _ensure_notion_key() -> None:
    if os.environ.get("NOTION_PROXY_API_KEY"):
        return
    for candidate in (
        Path("/opt/notion2api/.env"),
        Path("/opt/notion2api/.env.local"),
        Path("/etc/default/notion2api"),
    ):
        if not candidate.exists():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("API_KEY="):
                    os.environ["NOTION_PROXY_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
                    return
        except Exception:
            logger.debug("Could not read Notion API key from %s", candidate, exc_info=True)


def _env_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for candidate in (Path("/root/.hermes/.env"), Path("/opt/hermes-agent/.env")):
        if not candidate.exists():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, val = raw.split("=", 1)
                if key.strip() == name:
                    return val.strip().strip('"').strip("'")
        except Exception:
            logger.debug("Could not read %s from %s", name, candidate, exc_info=True)
    return ""


def _source_chat_id(source) -> str:
    for name in ("chat_id", "channel_id", "target_id", "id"):
        value = getattr(source, name, None)
        if value:
            return str(value)
    return ""


def _send_telegram_notice(chat_id: str, text: str) -> None:
    token = _env_value("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        return
    try:
        payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        logger.debug("Telegram plan-first notice failed", exc_info=True)


def _clean_text(value) -> str:
    return str(value or "").strip()


def _raw_reply_text(event) -> str:
    raw = getattr(event, "raw_message", None)
    replied = getattr(raw, "reply_to_message", None)
    if replied is None:
        return ""
    return _clean_text(getattr(replied, "text", None) or getattr(replied, "caption", None))


def _has_reply_context(event) -> bool:
    return bool(_clean_text(getattr(event, "reply_to_text", None)) or _raw_reply_text(event))


def _github_urls(value: str) -> list[str]:
    if not value:
        return []
    return [url.rstrip(".,;:)]}") for url in re.findall(r"https?://github\.com/[^\s)>'\"]+", value)]


def _apply_smart_policy_to_request(request_text: str) -> str:
    urls = _github_urls(request_text)
    repo_note = "\nGitHub URLs detected: " + ", ".join(urls) if urls else "\nGitHub URLs detected: none."
    return (
        f"{request_text}\n\n"
        "Mandatory planner policy for this /code request:\n"
        f"{SMART_TECHNICAL_POLICY}"
        f"{repo_note}\n"
    )


def _build_planning_input(event, text: str) -> str:
    reply_quote = _clean_text(getattr(event, "reply_to_text", None))
    reply_full = _raw_reply_text(event)
    if not reply_quote and not reply_full:
        return text

    parts = ["Telegram reply context:"]
    if reply_full:
        parts.append("FULL replied message:")
        parts.append(reply_full)
    if reply_quote and reply_quote != reply_full:
        parts.append("Selected quoted snippet:")
        parts.append(reply_quote)
    parts.append("Current user follow-up:")
    parts.append(text)
    parts.append(
        "Planning instruction: treat the current follow-up as a modification "
        "or continuation of the full replied message above. Do not plan from "
        "the follow-up alone."
    )
    return "\n".join(parts)


def _extract_code_prompt(text: str) -> str | None:
    raw = (text or "").strip()
    if raw == CODE_COMMAND:
        return ""
    if raw.startswith(CODE_COMMAND + " ") or raw.startswith(CODE_COMMAND + "\n"):
        return raw[len(CODE_COMMAND):].strip()
    return None


def _slugify_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:48].strip("-") or "code-project"


def _title_from_plan(plan_text: str, fallback: str) -> str:
    for line in (plan_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def _create_project_folder(plan_text: str, prompt: str) -> Path:
    title = _title_from_plan(plan_text, prompt[:80] or "code project")
    slug = _slugify_title(title)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = PROJECTS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{slug}-{ts}"
    if path.exists():
        path = root / f"{slug}-{ts}-{os.getpid()}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _materialize_project_plan(project_folder: Path, result, plan_text: str) -> tuple[Path, Path]:
    plan_copy = project_folder / "PLAN.md"
    state_copy = project_folder / "PLAN.state.json"
    plan_copy.write_text(plan_text, encoding="utf-8")
    try:
        state_copy.write_text(Path(result.state_path).read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        state_copy.write_text("{}\n", encoding="utf-8")
    return plan_copy, state_copy


def _write_active_plan_metadata(session_id: str, plan_path: Path, state_path: Path, project_folder: Path) -> None:
    ACTIVE_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if ACTIVE_PLAN_FILE.exists():
        try:
            existing = json.loads(ACTIVE_PLAN_FILE.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = existing
        except Exception:
            payload = {}
    entry = {
        "session_id": session_id,
        "active_plan_file": str(plan_path),
        "active_plan_state": str(state_path),
        "project_folder": str(project_folder),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload[session_id] = entry
    payload["current"] = entry
    tmp = ACTIVE_PLAN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ACTIVE_PLAN_FILE)


def _reset_for_new_code_session(gateway, session_store, source, session_id: str) -> str:
    if gateway is None or source is None:
        return session_id
    try:
        session_key = gateway._session_key_for_source(source)  # noqa: SLF001
    except Exception:
        session_key = session_id
    try:
        if hasattr(gateway, "_invalidate_session_run_generation"):
            gateway._invalidate_session_run_generation(session_key, reason="code_command_new_project")
        if hasattr(gateway, "_evict_cached_agent"):
            gateway._evict_cached_agent(session_key)
        if hasattr(gateway, "_queued_events"):
            gateway._queued_events.pop(session_key, None)
    except Exception:
        logger.debug("/code cache cleanup failed", exc_info=True)
    try:
        store = session_store or getattr(gateway, "session_store", None)
        if store is not None:
            entry = store.reset_session(session_key)
            if entry is not None and getattr(entry, "session_id", None):
                return entry.session_id
    except Exception:
        logger.debug("/code session reset failed", exc_info=True)
    return session_key


class _PlanPaths:
    def __init__(self, path: Path, state_path: Path, original_path: Path):
        self.path = path
        self.state_path = state_path
        self.original_path = original_path
        self.task_count = 0
        self.used_fallback = False


def _build_rewritten(*, planning_input: str, result, plan_text: str, project_folder: Path, session_id: str, used_fallback: bool, planner_error: str | None = None) -> str:
    error_line = f"Planner error: {planner_error}\n" if planner_error else ""
    return (
        f"{MARKER}\n"
        f"Current Plan File: {result.path}\n"
        f"Current Plan State: {result.state_path}\n"
        f"Original Notion Plan File: {getattr(result, 'original_path', result.path)}\n"
        f"Project Folder: {project_folder}\n"
        f"Plan Session ID: {session_id}\n"
        f"Tasks: {result.task_count}\n"
        f"Used fallback planner: {used_fallback}\n"
        f"{error_line}\n"
        "Yeu cau goc cua user:\n"
        f"{planning_input}\n\n"
        "Ke hoach bat buoc phai theo truoc khi code/tool-call:\n"
        f"{plan_text}\n\n"
        "Chi dan thuc thi bat buoc:\n"
        "- Ton trong stack/ngon ngu Notion plan da chon theo /code technical planning policy; khong tu doi sang Go/Rust hoac stack khac neu khong co ly do ky thuat manh va noi ro trong cau tra loi.\n"
        "- Neu PLAN.md thieu chi tiet module/function/script/test, bo sung chi tiet vao PLAN.md truoc khi code, nhung van chi dung Current Plan File va Project Folder.\n"
        f"- Implement toan bo code trong Project Folder: {project_folder}.\n"
        f"- Truoc moi terminal command, chay: cd {project_folder} && export PATH={SANE_PATH}.\n"
        f"- Neu tool khong ho tro cd, dung absolute path ben trong {project_folder}.\n"
        f"- Chi doc dung Current Plan File: {result.path}.\n"
        "- Ban goc trong ~/.hermes/plans chi de audit; khong doc no bang tool neu da co PLAN.md trong Project Folder.\n"
        "- Cam glob/list/search/read plan khac trong /root/.hermes/plans hoac ~/.hermes/plans.\n"
        "- Khong su dung plan cu trong context; neu thay duong dan plan khac, bo qua.\n"
        "- Sau moi task, cap nhat tien do bang task id da xong trong cau tra loi.\n"
        "- Khi implement va test local xong, hay hoi user dung cau nay: "
        f"Du an da implement xong trong {project_folder}. Ban co muon deploy ngay len VPS de chay thu khong?\n"
        "- Khong tu deploy neu user chua xac nhan ro trong yeu cau hien tai.\n"
    )


def _on_pre_gateway_dispatch(event, gateway=None, session_store=None):
    text = (getattr(event, "text", "") or "").strip()
    if not text or text.startswith("!") or MARKER in text:
        return {"action": "allow"}

    code_prompt = _extract_code_prompt(text)
    if code_prompt is None:
        # v1.7 project isolation: normal chat does not trigger plan-first.
        return {"action": "allow"}
    if not code_prompt:
        return {"action": "skip", "reason": "empty_code_prompt"}

    source = getattr(event, "source", None)
    chat_id = _source_chat_id(source)

    try:
        if gateway is not None and source is not None:
            session_key = gateway._session_key_for_source(source)  # noqa: SLF001
            running = getattr(gateway, "_running_agents", {})
            if session_key in running:
                _send_telegram_notice(chat_id, "Dang co agent chay trong session nay. Hay cho xong hoac dung /stop roi gui lai /code.")
                return {"action": "skip", "reason": "agent_running"}
        else:
            session_key = "gateway"
    except Exception:
        session_key = "gateway"

    try:
        from hpf_gateway.config_loader import default_plan_first_config
        from hpf_gateway.plan_pipeline import notion_plan_to_md
        from hpf_gateway.provider_client import ProviderClient
    except Exception as exc:
        logger.warning("plan-first-router import failed: %s", exc)
        _send_telegram_notice(chat_id, f"/code loi import plan-first-router: {exc}")
        return {"action": "skip", "reason": "import_failed"}

    session_id = session_key
    if not _has_reply_context(event):
        session_id = _reset_for_new_code_session(gateway, session_store, source, session_key)
    planning_input = _apply_smart_policy_to_request(_build_planning_input(event, code_prompt))

    _ensure_notion_key()
    try:
        _send_telegram_notice(chat_id, "Da nhan /code. Hermes dang tao Notion plan va project folder moi, co the mat 30-240 giay.")
        result = notion_plan_to_md(
            idea=planning_input,
            session_id=session_id,
            config=default_plan_first_config(),
            client=ProviderClient(timeout_seconds=int(os.environ.get("HERMES_PLAN_TIMEOUT_SECONDS", "240"))),
            dry_run=False,
        )
        plan_text = result.path.read_text(encoding="utf-8")
        project_folder = _create_project_folder(plan_text, planning_input)
        project_plan, project_state = _materialize_project_plan(project_folder, result, plan_text)
        prompt_result = _PlanPaths(project_plan, project_state, result.path)
        prompt_result.task_count = result.task_count
        prompt_result.used_fallback = result.used_fallback
        _write_active_plan_metadata(session_id, project_plan, project_state, project_folder)
        logger.info("/code generated plan=%s project_plan=%s project=%s tasks=%s fallback=%s", result.path, project_plan, project_folder, result.task_count, result.used_fallback)
        _send_telegram_notice(chat_id, f"Plan da san sang: {result.task_count} tasks. Project folder: {project_folder}. Dang chuyen qua coding lane.")
        return {"action": "rewrite", "text": _build_rewritten(planning_input=planning_input, result=prompt_result, plan_text=plan_text, project_folder=project_folder, session_id=session_id, used_fallback=result.used_fallback)}
    except Exception as exc:
        logger.warning("/code Notion planning failed, generating local fallback plan: %s", exc, exc_info=True)
        try:
            result = notion_plan_to_md(
                idea=planning_input,
                session_id=session_id,
                config=default_plan_first_config(),
                client=ProviderClient(timeout_seconds=5),
                dry_run=True,
            )
            plan_text = result.path.read_text(encoding="utf-8")
            project_folder = _create_project_folder(plan_text, planning_input)
            project_plan, project_state = _materialize_project_plan(project_folder, result, plan_text)
            prompt_result = _PlanPaths(project_plan, project_state, result.path)
            prompt_result.task_count = result.task_count
            prompt_result.used_fallback = True
            _write_active_plan_metadata(session_id, project_plan, project_state, project_folder)
            _send_telegram_notice(chat_id, f"Notion planner loi/timeout, da tao fallback plan local: {result.task_count} tasks. Project folder: {project_folder}.")
            return {"action": "rewrite", "text": _build_rewritten(planning_input=planning_input, result=prompt_result, plan_text=plan_text, project_folder=project_folder, session_id=session_id, used_fallback=True, planner_error=f"{type(exc).__name__}: {exc}")}
        except Exception as fallback_exc:
            logger.error("/code fallback plan generation also failed", exc_info=True)
            _send_telegram_notice(chat_id, f"/code loi: Notion planner va fallback planner deu fail: {fallback_exc}")
            return {"action": "skip", "reason": "planner_failed"}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
