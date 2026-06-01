# windsurf-notion-llm-hermes

Dual LLM provider setup for Hermes Agent Gateway - WindsurfAPI primary with tool calling plus Notion2API fallback.

## Version

Current repo config targets **Hermes 1.7 - Pinned Model Mode**.

Pinned mode keeps the full provider and fallback configuration in place, but the effective default route is locked to:

```text
provider: windsurf
model: deepseek-v4-pro
backend: http://127.0.0.1:3003/v1
```

Disable the temporary lock by setting:

```yaml
routing_lock:
  enabled: false
```

## Architecture

```text
Telegram -> Hermes Gateway -> WindsurfAPI (port 3003) -> Windsurf Cloud
                         \-> Notion2API (port 4200) -> Notion AI fallback
```

## Quick Setup

```bash
# 1. Clone
git clone <repo-url> /opt/windsurf-notion-llm-hermes
cd /opt/windsurf-notion-llm-hermes

# 2. Run setup
bash scripts/setup.sh

# 3. Add Windsurf account
bash scripts/add-windsurf-account.sh <your-token>

# 4. Add Notion token
bash scripts/update-notion-token.sh <token_v2> <user_id>

# 5. Apply Super Kaka persona
bash scripts/apply-persona.sh

# 6. Apply Hermes 1.7 pinned routing lock on a VPS
bash scripts/apply-v1.7-routing-lock.sh

# 7. Apply /code plan-first project isolation and smart planning policy
bash scripts/apply-v1.7-code-mode.sh
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| windsurf-api | 3003 | WindsurfAPI proxy and account pool |
| notion2api | 4200 | Notion AI proxy fallback |
| hermes-gateway | - | Hermes Agent Gateway |

## Models

### v1.7 pinned model
- DeepSeek V4 Pro: `deepseek-v4-pro`

### Other configured Windsurf models
- Claude Opus 4.6/4.7 thinking variants
- GPT 5.4/5.5 variants
- Gemini 2.5/3.0/3.1 variants
- Kimi, GLM, Grok, MiniMax, SWE models

## Important Config Notes

### `/code` Plan-First Project Isolation

Hermes 1.7 adds a dedicated coding command:

```text
/code <project request>
```

Normal chat stays conversational and does not create a plan. `/code` creates a fresh Notion/fallback plan, creates a new project folder under `/opt/hermes-agent/projects/<slug>-<timestamp>`, pins the current plan file into the coding prompt, and blocks stale reads from old `~/.hermes/plans` files.

The planner also receives a fixed smart technical policy:

- GitHub URLs in the prompt are treated as the source of truth for stack, package manager, framework, style, and layout.
- Existing repo ecosystem is preferred for maintainability.
- Go/Rust are proposed only when the repo/user request or technical constraints justify them.
- Plans must include module/function/script-level tasks, commands, tests, deploy notes, and 2026-stable best practices.

Run this on the VPS to apply the live-tested patch set:

```bash
bash scripts/apply-v1.7-code-mode.sh
```

### Hermes 1.7 Pinned Model Mode

`config/hermes-config.yaml` includes:

```yaml
routing_lock:
  enabled: true
  provider: windsurf
  backend: windsurf-proxy
  model: deepseek-v4-pro
  rotate_accounts: true
  allow_backstop: false
  keep_signal_heal: true
  validate_on_start: true
```

In this repository the lock is applied at config/runtime level. The WindsurfAPI account pool still rotates accounts internally on quota/account errors, but Hermes' default provider/model is pinned to Windsurf + DeepSeek V4 Pro.

Run this on the VPS to enforce the same state in live files:

```bash
bash scripts/apply-v1.7-routing-lock.sh
```

### `discover_models: false`

WindsurfAPI exposes a large model catalog via `/v1/models`. Without `discover_models: false`, Hermes can replace the curated model list with the full catalog. Keep this set under the `windsurf` provider.

### Model Persistence After Restart

By default, Hermes can reset to `default_model` after gateway restart. To persist model selection, patch `gateway/run.py` to save/load `_session_model_overrides` to `~/.hermes/model_overrides.json`. See `scripts/patch-model-persist.sh`.

## Environment Variables

See `config/*.env.example` for all options.

## License

MIT
