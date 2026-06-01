from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .checklist_updater import count_tasks, plan_content_hash
from .config_loader import PlanFirstConfig
from .provider_client import ProviderClient, extract_text
from .types import PlanResult


PLAN_SYSTEM_PROMPT = """You are a senior 2026 technical planning expert for a Hermes coding agent.
Return markdown with exactly these headings and no extra top-level headings:
# {short title}
## Goal
## Context
## Tasks
## Tool Plan
## Acceptance Criteria
## Risks

Planning policy:
- If the request contains GitHub repository URLs, treat those repositories as the source of truth for language, framework, package manager, folder layout, conventions, and compatibility. The first task must inspect/clone/read the repo before implementation.
- Prefer the repository's existing ecosystem (Node/TypeScript, Python, Go, Rust, etc.) for maintainability. Do not suggest Go or Rust unless the repo already uses them, the user explicitly asks for them, or there is a concrete reason such as performance, single-binary deploy, concurrency, memory safety, CLI/agent infrastructure, or low-resource VPS deployment.
- If no repo is provided, choose the most pragmatic stable stack for the requested product. Use modern stable 2026 best practices; avoid beta/experimental dependencies unless the user asks for them or they clearly reduce risk.
- In ## Context, include repo/stack inference and language-choice rationale.
- In ## Tasks, use executable checklist items with IDs like **T1**; each task must mention concrete files/modules/functions/scripts to create or inspect.
- In ## Tool Plan, include exact commands/scripts, repo inspection order, build/test commands, and deploy-readiness checks.
- In ## Acceptance Criteria, include local run/test success and deploy-ready criteria.
- In ## Risks, include dependency/version, tool-calling/provider, repo compatibility, and VPS deployment risks.
- Plans should be specific enough that a coding agent can implement without asking which language, framework, files, functions, scripts, or tests to use."""


def slugify(value: str) -> str:
    lowered = value.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return normalized[:48] or "hermes-plan"


def extract_github_urls(value: str) -> list[str]:
    if not value:
        return []
    urls = re.findall(r"https?://github\.com/[^\s)>'\"]+", value)
    cleaned = []
    for url in urls:
        cleaned.append(url.rstrip(".,;:)]}"))
    return cleaned


def validate_plan(markdown: str, required_headings: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for heading in required_headings:
        if heading == "# ":
            if not markdown.lstrip().startswith("# "):
                errors.append("missing title heading")
        elif heading not in markdown:
            errors.append(f"missing heading: {heading}")
    if count_tasks(markdown) == 0:
        errors.append("missing checklist tasks")
    return errors


def notion_plan_to_md(
    idea: str,
    session_id: str,
    config: PlanFirstConfig,
    client: ProviderClient,
    dry_run: bool = False,
) -> PlanResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(idea)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    plan_path = config.output_dir / f"{slug}-{timestamp}.md"
    state_path = plan_path.with_suffix(".state.json")
    markdown = _fallback_plan(idea) if dry_run else _call_planner(idea, session_id, config, client)
    errors = validate_plan(markdown, config.required_headings)
    if errors:
        markdown = _fallback_plan(idea, errors)
    plan_path.write_text(markdown, encoding="utf-8")
    state_path.write_text(
        _initial_state_json(plan_content_hash(plan_path)),
        encoding="utf-8",
    )
    return PlanResult(
        path=plan_path,
        state_path=state_path,
        slug=slug,
        task_count=count_tasks(markdown),
        used_fallback=bool(errors) or dry_run,
    )


def _call_planner(idea: str, session_id: str, config: PlanFirstConfig, client: ProviderClient) -> str:
    messages = [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": f"Session: {session_id}\nRequest: {idea}"},
    ]
    response = client.chat_completion(config.provider, config.endpoint, config.model_alias, messages)
    text = extract_text(response)
    return text if text.strip() else _fallback_plan(idea, ["empty planner response"])


def _fallback_plan(idea: str, errors: list[str] | None = None) -> str:
    note = ""
    if errors:
        note = "\n- Planner fallback reason: " + "; ".join(errors)
    github_urls = extract_github_urls(idea)
    has_repo = bool(github_urls)
    repo_line = ", ".join(github_urls) if github_urls else "None provided"
    title = slugify(idea).replace("-", " ").title()
    if has_repo:
        stack_policy = (
            "Inspect the GitHub repo first and follow its existing language, framework, "
            "package manager, folder layout, and conventions. Only choose Go/Rust if the repo "
            "already uses them or a concrete performance/binary/concurrency reason appears during inspection."
        )
        t1 = f"Clone or inspect the GitHub repository URLs: {repo_line}; identify language, framework, package manager, entrypoints, scripts, and test commands"
    else:
        stack_policy = (
            "No repo was provided. Choose the most pragmatic stable 2026 stack for the product; avoid beta/experimental dependencies unless they clearly reduce implementation risk."
        )
        t1 = "Infer the best stable 2026 stack from the requested product; document language/framework/package-manager choice and alternatives rejected"
    return f"""# {title}

## Goal
Implement the requested project in an isolated Hermes `/code` project folder with a technically specific, deploy-ready plan.

## Context
- Request: {idea}{note}
- GitHub repositories: {repo_line}
- Stack policy: {stack_policy}
- Language choice rationale: choose compatibility with the repo first; otherwise choose the simplest stable stack that satisfies product, runtime, and VPS deployment constraints.

## Tasks
- [ ] **T1**: {t1} `[priority:high]` `[tools:terminal,read_file]`
- [ ] **T2**: Create the project scaffold in the assigned Project Folder, including config files, package/build scripts, and a README with local run instructions `[priority:high]` `[tools:terminal,write_file]`
- [ ] **T3**: Implement core modules/functions with explicit inputs, outputs, error handling, and edge cases described in code comments only where useful `[priority:high]` `[tools:write_file,patch]`
- [ ] **T4**: Add focused tests or smoke scripts for the main workflow, failure cases, and deployment readiness `[priority:high]` `[tools:write_file,terminal]`
- [ ] **T5**: Run install/build/test locally, fix failures, and produce a concise completion note asking whether to deploy to VPS `[priority:high]` `[tools:terminal]`

## Tool Plan
T1:
- If GitHub URLs exist, run `git clone <repo-url>` or inspect the repo, then read manifest files such as package.json, pyproject.toml, go.mod, Cargo.toml, README, and existing scripts.
- If no repo exists, create a minimal scaffold directly in the Project Folder using the chosen stable stack.
T2:
- Create project files and scripts inside the Project Folder only.
T3:
- Implement named modules/functions from the selected stack; preserve repo conventions when extending an existing repo.
T4:
- Add tests or smoke scripts matching the chosen language/framework.
T5:
- Run the exact build/test commands discovered or created; record any deploy command candidates without deploying automatically.

## Acceptance Criteria
- [ ] Project code exists only inside the assigned Project Folder unless the plan explicitly clones a repo there.
- [ ] Stack/language choice follows repo compatibility first or includes a clear rationale when no repo exists.
- [ ] Local install/build/test or smoke verification succeeds.
- [ ] README or equivalent instructions explain local run and VPS deploy candidate commands.
- [ ] Final assistant message asks whether the user wants immediate VPS deployment.

## Risks
- GitHub repo may use outdated or undocumented scripts; inspect manifests before choosing commands.
- Provider/tool-calling may emit malformed tool calls; retry with simpler commands and verify files on disk.
- Dependency versions may have changed by 2026; prefer stable/latest-compatible versions and pin where useful.
- VPS deployment may need ports, firewall, env vars, or process manager setup; do not deploy without user confirmation.
"""


def _initial_state_json(content_hash: str) -> str:
    return (
        "{\n"
        '  "completed_tasks": 0,\n'
        '  "failed_tasks": 0,\n'
        '  "skipped_tasks": 0,\n'
        '  "task_status": {},\n'
        f'  "content_hash": "{content_hash}"\n'
        "}\n"
    )
