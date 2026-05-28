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

## Environment Variables

See `config/*.env.example` for all options.

## License
MIT
