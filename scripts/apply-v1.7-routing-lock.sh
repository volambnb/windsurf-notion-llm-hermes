#!/bin/bash
set -euo pipefail

HERMES_CONFIG="${HERMES_CONFIG:-/root/.hermes/config.yaml}"
WINDSURF_ROOT="${WINDSURF_ROOT:-/opt/WindsurfAPI}"
WINDSURF_MODELS="$WINDSURF_ROOT/src/models.js"
WINDSURF_ENV="$WINDSURF_ROOT/.env"
PINNED_MODEL="${PINNED_MODEL:-deepseek-v4-pro}"
PINNED_UID="${PINNED_UID:-deepseek-v4}"

ts="$(date +%Y%m%d_%H%M%S)"

echo "=== Hermes 1.7 routing lock ==="
echo "Hermes config: $HERMES_CONFIG"
echo "Windsurf root: $WINDSURF_ROOT"
echo "Pinned model:  $PINNED_MODEL -> $PINNED_UID"

if [ ! -f "$HERMES_CONFIG" ]; then
  echo "ERROR: Hermes config not found: $HERMES_CONFIG" >&2
  exit 1
fi
if [ ! -f "$WINDSURF_MODELS" ]; then
  echo "ERROR: Windsurf models file not found: $WINDSURF_MODELS" >&2
  exit 1
fi

cp "$HERMES_CONFIG" "$HERMES_CONFIG.bak.v1.7-$ts"
cp "$WINDSURF_MODELS" "$WINDSURF_MODELS.bak.v1.7-$ts"
[ -f "$WINDSURF_ENV" ] && cp "$WINDSURF_ENV" "$WINDSURF_ENV.bak.v1.7-$ts"

python3 - "$HERMES_CONFIG" "$WINDSURF_MODELS" "$WINDSURF_ENV" "$PINNED_MODEL" "$PINNED_UID" <<'PY'
from pathlib import Path
import re
import sys

hermes = Path(sys.argv[1])
models = Path(sys.argv[2])
env = Path(sys.argv[3])
pinned_model = sys.argv[4]
pinned_uid = sys.argv[5]

def replace_top_model(s: str) -> str:
    s = re.sub(r"(?m)^model:\n(?:  .+\n)+", f"model:\n  default: {pinned_model}\n  provider: windsurf\n  base_url: http://127.0.0.1:3003/v1\n", s, count=1)
    return s

def ensure_routing_lock(s: str) -> str:
    block = f"""routing_lock:
  enabled: true
  provider: windsurf
  backend: windsurf-proxy
  model: {pinned_model}
  rotate_accounts: true
  allow_backstop: false
  keep_signal_heal: true
  validate_on_start: true

"""
    if re.search(r"(?m)^routing_lock:", s):
        s = re.sub(r"(?ms)^routing_lock:\n(?:  .+\n|\n)*?(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)", block, s, count=1)
    else:
        insert_at = s.find("providers:")
        s = s[:insert_at] + block + s[insert_at:] if insert_at >= 0 else s + "\n" + block
    return s

def ensure_windsurf_defaults(s: str) -> str:
    s = re.sub(r"(?m)^  windsurf:\n((?:    .+\n)+)", lambda m: m.group(0).replace("default_model: claude-sonnet-4.6", f"default_model: {pinned_model}"), s, count=1)
    if f"    default_model: {pinned_model}" not in s:
        s = s.replace("    key_env: WINDSURF_API_KEY\n", f"    key_env: WINDSURF_API_KEY\n    default_model: {pinned_model}\n", 1)
    if f"      - {pinned_model}\n" not in s:
        marker = "    models:\n"
        idx = s.find(marker, s.find("  windsurf:"))
        if idx >= 0:
            idx += len(marker)
            s = s[:idx] + f"      - {pinned_model}\n" + s[idx:]
    s = normalize_windsurf_model_indent(s)
    return s

def normalize_windsurf_model_indent(s: str) -> str:
    lines = s.splitlines()
    out = []
    in_windsurf = False
    in_models = False
    for line in lines:
        if line == "  windsurf:":
            in_windsurf = True
            in_models = False
            out.append(line)
            continue
        if in_windsurf and line.startswith("  ") and not line.startswith("    ") and line != "  windsurf:":
            in_windsurf = False
            in_models = False
            out.append(line)
            continue
        if in_windsurf and line == "    models:":
            in_models = True
            out.append(line)
            continue
        if in_models and line.startswith("    - "):
            out.append("  " + line)
            continue
        out.append(line)
    return "\n".join(out) + "\n"

def ensure_aux_blocks(s: str) -> str:
    if "tier_models:" not in s:
        s += f"""

tier_models:
  tier1_default: {pinned_model}
  tier2_cheap: gemini-3.0-flash-high
  tier4_local: notion-agent-opus
  advisor: opus-4.8
"""
    if "model_bootstrap:" not in s:
        s += """

model_bootstrap:
  enabled: true
  run_on_start: true
  discovery_path: /models
  ttl_seconds: 300
  stale_seconds: 1800
  per_account_timeout_s: 8
  prefer_more_accounts: true
"""
    if "model_fallback:" not in s:
        s += """

model_fallback:
  - windsurf
  - notion-proxy
  - nvidia
"""
    return s

s = hermes.read_text()
s = replace_top_model(s)
s = ensure_routing_lock(s)
s = ensure_windsurf_defaults(s)
s = ensure_aux_blocks(s)
hermes.write_text(s)

m = models.read_text()
entry = f"  '{pinned_model}':                {{ name: '{pinned_model}',                provider: 'deepseek', enumValue: 0,   modelUid: '{pinned_uid}', credit: 1 }},\n"
if f"'{pinned_model}'" not in m:
    marker = "  // ── DeepSeek"
    idx = m.find(marker)
    if idx >= 0:
        line_end = m.find("\n", idx) + 1
        m = m[:line_end] + entry + m[line_end:]
    else:
        marker = "export const MODEL_TIER_ACCESS"
        idx = m.find(marker)
        m = m[:idx] + entry + "\n" + m[idx:]
models.write_text(m)

if env.exists():
    e = env.read_text()
    if re.search(r"(?m)^DEFAULT_MODEL=", e):
        e = re.sub(r"(?m)^DEFAULT_MODEL=.*", f"DEFAULT_MODEL={pinned_model}", e)
    else:
        e += f"\nDEFAULT_MODEL={pinned_model}\n"
    env.write_text(e)
PY

node --check "$WINDSURF_MODELS"

echo "Validating Windsurf /v1/models..."
api_key=""
if [ -f "$WINDSURF_ENV" ]; then
  api_key="$(grep -E '^API_KEY=' "$WINDSURF_ENV" | head -n1 | cut -d= -f2- || true)"
fi
if [ -n "$api_key" ]; then
  if curl -fsS -H "Authorization: Bearer $api_key" http://127.0.0.1:3003/v1/models 2>/dev/null | grep -q "\"id\":\"$PINNED_MODEL\""; then
    echo "OK: $PINNED_MODEL is already visible from /v1/models."
  else
    echo "WARN: $PINNED_MODEL not visible yet. Restart windsurf-api.service, then check /v1/models."
  fi
else
  echo "WARN: API_KEY not found in $WINDSURF_ENV; skipped /v1/models validation."
fi

if command -v systemctl >/dev/null 2>&1; then
  echo "Restarting services..."
  systemctl restart windsurf-api.service || true
  systemctl restart hermes-gateway.service || true
fi

echo "Done. Backups:"
echo "  $HERMES_CONFIG.bak.v1.7-$ts"
echo "  $WINDSURF_MODELS.bak.v1.7-$ts"
