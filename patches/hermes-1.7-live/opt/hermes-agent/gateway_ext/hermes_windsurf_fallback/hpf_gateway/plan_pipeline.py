from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .checklist_updater import count_tasks, plan_content_hash
from .config_loader import PlanFirstConfig
from .provider_client import ProviderClient, extract_text
from .types import PlanResult


PLAN_SYSTEM_PROMPT = """You are a senior 2026 technical planning expert for a coding agent.
Return markdown with exactly these headings and no extra top-level headings:
# {short title}
## Goal
## Context
## Tasks
## Tool Plan
## Acceptance Criteria
## Risks

Planning policy:
- If the request contains GitHub repository URLs, treat those repositories as the source of truth for language, framework, package manager, folder layout, conventions, APIs, scripts, tests, deployment style, and compatibility. The first task must inspect/clone/read the repo before implementation.
- Prefer the repository's existing ecosystem for maintainability. Do not suggest Go or Rust unless the repo already uses them, the user explicitly asks for them, or there is a concrete reason such as performance, single-binary deploy, concurrency, memory safety, CLI/agent infrastructure, or low-resource VPS deployment.
- If the request does not contain a GitHub URL and is only an idea or product description, first normalize the idea into a precise technical product brief: target users, core workflow, required screens/APIs/modules, data model, runtime constraints, deployment target, and non-goals.
- For idea-only requests, search GitHub for mature, relevant repositories whose technical purpose, architecture, or product behavior is similar or adjacent. Use these repositories as reference material, not as mandatory dependencies. Prefer actively maintained repos with clear README, package files, scripts, tests, and deploy docs.
- For each selected reference repo, analyze its stack, folder layout, core modules, important functions/classes, scripts, tests, build/deploy flow, strengths, weaknesses, and which ideas should or should not be reused.
- Choose the most pragmatic stable stack for the requested product after comparing the normalized product brief with the GitHub references. Use modern stable 2026 best practices; avoid beta/experimental dependencies unless the user asks for them or they clearly reduce risk.
- In ## Context, include: normalized technical brief, repo/stack inference, GitHub reference repos inspected or to inspect, language-choice rationale, and why the final stack is appropriate.
- In ## Tasks, use executable checklist items with IDs like **T1**. Each task must mention concrete files/modules/functions/scripts to create, inspect, or modify.
- In ## Tool Plan, include exact commands/scripts, GitHub search terms, repo inspection order, clone/read commands, package-manager commands, build/test commands, and deploy-readiness checks.
- In ## Acceptance Criteria, include local run success, test success, implementation completeness, UX/API behavior, and deploy-ready criteria.
- In ## Risks, include dependency/version risk, GitHub reference mismatch risk, tool-calling/provider risk, repo compatibility risk, security/secrets risk, and VPS deployment risk.
- Plans must be specific enough that a coding agent can implement without asking which language, framework, files, functions, scripts, tests, or deploy commands to use."""


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
            "package manager, folder layout, APIs, scripts, tests, deployment style, and conventions. Only choose Go/Rust if the repo "
            "already uses them or a concrete performance/binary/concurrency reason appears during inspection."
        )
        t1 = f"Clone or inspect the GitHub repository URLs: {repo_line}; identify language, framework, package manager, entrypoints, scripts, and test commands"
    else:
        stack_policy = (
            "No repo was provided. Normalize the idea into a technical product brief, search GitHub for mature similar repositories, analyze their stack/scripts/tests/deploy flow as references, then choose the most pragmatic stable 2026 stack. Reference repos guide architecture but are not mandatory dependencies."
        )
        t1 = "Normalize the product idea into target users, core workflow, screens/APIs/modules, data model, runtime constraints, deployment target, and non-goals"
    return f"""# {title}

## Goal
Implement the requested project in an isolated Hermes `/code` project folder with a technically specific, deploy-ready plan.

## Context
- Request: {idea}{note}
- GitHub repositories: {repo_line}
- Stack policy: {stack_policy}
- Normalized technical brief: describe target users, main workflow, modules/screens/APIs, data model, runtime constraints, deployment target, and non-goals before implementation.
- GitHub reference strategy: if no repo URL exists, search for mature similar repositories and use them as architecture/script/test references only.
- Language choice rationale: choose compatibility with the provided repo first; otherwise compare the normalized brief with GitHub references and choose the simplest stable stack that satisfies product, runtime, and VPS deployment constraints.

## Tasks
- [ ] **T1**: {t1} `[priority:high]` `[tools:terminal,read_file]`
- [ ] **T2**: Search GitHub reference repositories when no repo URL exists, or inspect the provided repo when URLs exist; document selected repo references, manifests, scripts, tests, core modules, strengths, weaknesses, and reuse boundaries `[priority:high]` `[tools:terminal,read_file]`
- [ ] **T3**: Create the project scaffold in the assigned Project Folder, including config files, package/build scripts, and a README with local run instructions `[priority:high]` `[tools:terminal,write_file]`
- [ ] **T4**: Implement core modules/functions with explicit inputs, outputs, error handling, and edge cases described in code comments only where useful `[priority:high]` `[tools:write_file,patch]`
- [ ] **T5**: Add focused tests or smoke scripts for the main workflow, failure cases, and deployment readiness `[priority:high]` `[tools:write_file,terminal]`
- [ ] **T6**: Run install/build/test locally, fix failures, and produce a concise completion note asking whether to deploy to VPS `[priority:high]` `[tools:terminal]`

## Tool Plan
T1:
- If GitHub URLs exist, run `git clone <repo-url>` or inspect the repo, then read manifest files such as package.json, pyproject.toml, go.mod, Cargo.toml, README, and existing scripts.
- If no repo exists, write a short technical brief in `PLAN.md` covering users, workflow, screens/APIs/modules, data model, runtime constraints, deployment target, and non-goals.
T2:
- If no repo URL exists, run GitHub searches using terms derived from the normalized brief, inspect 2-3 mature repositories, and record stack/layout/scripts/tests/deploy patterns to reuse or reject. If repo URLs exist, complete source-of-truth inspection of those repos.
T3:
- Create project files and scripts inside the Project Folder only, using the selected stack.
T4:
- Implement named modules/functions from the selected stack; preserve repo conventions when extending an existing repo.
T5:
- Add tests or smoke scripts matching the chosen language/framework.
T6:
- Run the exact build/test commands discovered or created; record any deploy command candidates without deploying automatically.

## Acceptance Criteria
- [ ] Project code exists only inside the assigned Project Folder unless the plan explicitly clones a repo there.
- [ ] Stack/language choice follows repo compatibility first, or for idea-only requests follows a normalized technical brief plus GitHub reference analysis.
- [ ] Local install/build/test or smoke verification succeeds.
- [ ] README or equivalent instructions explain local run and VPS deploy candidate commands.
- [ ] Final assistant message asks whether the user wants immediate VPS deployment.

## Risks
- GitHub repo may use outdated or undocumented scripts; inspect manifests before choosing commands.
- Idea-only GitHub references may not exactly match the target product; reuse patterns selectively and do not copy unrelated architecture.
- Provider/tool-calling may emit malformed tool calls; retry with simpler commands and verify files on disk.
- Dependency versions may have changed by 2026; prefer stable/latest-compatible versions and pin where useful.
- Secrets or copied config examples from reference repos may be unsafe; create clean env examples and never hardcode credentials.
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
