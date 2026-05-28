# windsurf-notion-llm-hermes

Dual LLM provider setup for Hermes Agent Gateway — WindsurfAPI (primary, tool calling) + Notion2API (fallback, chat only).

## Architecture

```
Telegram ──► Hermes Gateway ──┬──► WindsurfAPI (port 3003) ──► Windsurf Cloud
                              │     ✅ Tool calling (Claude/GPT)
                              │     ✅ 100+ models, account pool
                              │
                              └──► Notion2API (port 4200) ──► Notion AI
                                    ❌ No tool calling
                                    ✅ Free via Notion subscription
```

## Quick Setup

```bash
# 1. Clone
git clone <repo-url> /opt/windsurf-notion-llm-hermes
cd /opt/windsurf-notion-llm-hermes

# 2. Run setup
bash scripts/setup.sh

# 3. Add Windsurf account (get token from https://windsurf.com/show-auth-token)
bash scripts/add-windsurf-account.sh <your-token>

# 4. Add Notion token (from browser cookies)
bash scripts/update-notion-token.sh <token_v2> <user_id>

# 5. Apply Super Kaka persona (SOUL, memory, skill)
bash scripts/apply-persona.sh
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| windsurf-api | 3003 | WindsurfAPI proxy (primary) |
| notion2api | 4200 | Notion AI proxy (fallback) |
| hermes-gateway | - | Hermes Agent Gateway |

## Models

### Pro (uses Windsurf quota)
- Claude Opus 4.6/4.7 (thinking variants)
- GPT 5.3/5.4/5.5

### Free (no quota)
- Kimi K2/K2.5/K2.6
- Gemini 2.5-flash, 3.0-flash
- GLM 4.7/5/5.1
- Grok 3
- MiniMax M2.5

## Important Config Notes

### `discover_models: false`
WindsurfAPI exposes 130+ models via `/v1/models`. Without `discover_models: false`,
Hermes will override your curated model list with the full catalog. Always set this
in `config/hermes-config.yaml` under the windsurf provider.

### Model Persistence After Restart
By default, Hermes resets to `default_model` after gateway restart. To persist the
user's model selection, patch `gateway/run.py` to save/load `_session_model_overrides`
to `~/.hermes/model_overrides.json`. See `scripts/patch-model-persist.sh`.

## Environment Variables

See `config/*.env.example` for all options.

## License
MIT
