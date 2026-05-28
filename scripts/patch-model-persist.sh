#!/bin/bash
set -e

# Patch Hermes gateway/run.py to persist model overrides across restarts.
# This adds _load_model_overrides() and _save_model_overrides() methods
# to GatewayRunner, saving selections to ~/.hermes/model_overrides.json.

HERMES_AGENT="${HERMES_AGENT_PATH:-/opt/hermes-agent}"
RUN_PY="$HERMES_AGENT/gateway/run.py"
MODEL_SWITCH_PY="$HERMES_AGENT/hermes_cli/model_switch.py"

if [ ! -f "$RUN_PY" ]; then
  echo "ERROR: $RUN_PY not found. Set HERMES_AGENT_PATH."
  exit 1
fi

# Check if already patched
if grep -q '_load_model_overrides' "$RUN_PY"; then
  echo "Already patched (model persistence). Skipping."
else
  python3 << 'PYEOF'
import os

RUN_PY = os.environ.get("HERMES_AGENT_PATH", "/opt/hermes-agent") + "/gateway/run.py"

with open(RUN_PY, 'r') as f:
    content = f.read()

# Patch 1: Add _load call in __init__
init_marker = 'self._session_model_overrides: Dict[str, Dict[str, str]] = {}'
if '_load_model_overrides' not in content:
    content = content.replace(
        init_marker,
        init_marker + '\n        self._load_model_overrides()'
    )

# Patch 2: Add methods before _wire_teams_pipeline_runtime
methods_block = '''    def _load_model_overrides(self):
        """Load persisted model overrides from disk."""
        _path = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "model_overrides.json")
        try:
            if os.path.exists(_path):
                with open(_path, "r") as _f:
                    self._session_model_overrides = json.load(_f)
        except Exception:
            pass

    def _save_model_overrides(self):
        """Persist model overrides to disk."""
        _path = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "model_overrides.json")
        try:
            with open(_path, "w") as _f:
                json.dump(self._session_model_overrides, _f)
        except Exception:
            pass

'''

target = '    def _wire_teams_pipeline_runtime(self) -> None:'
if 'def _load_model_overrides' not in content:
    content = content.replace(target, methods_block + target)

# Patch 3: Add _save calls after override assignments
old1 = '''_self._session_model_overrides[_session_key] = {
                            "model": result.new_model,
                            "provider": result.target_provider,
                            "api_key": result.api_key,
                            "base_url": result.base_url,
                            "api_mode": result.api_mode,
                        }'''
new1 = old1 + '\n                        _self._save_model_overrides()'
if '_self._save_model_overrides()' not in content:
    content = content.replace(old1, new1, 1)

old2 = '''self._session_model_overrides[session_key] = {
            "model": result.new_model,
            "provider": result.target_provider,
            "api_key": result.api_key,
            "base_url": result.base_url,
            "api_mode": result.api_mode,
        }'''
new2 = old2 + '\n        self._save_model_overrides()'
if 'self._save_model_overrides()' not in content:
    content = content.replace(old2, new2, 1)

# Patch 4: Save on pop
old_pop = 'self._session_model_overrides.pop(session_key, None)'
new_pop = 'self._session_model_overrides.pop(session_key, None); self._save_model_overrides()'
content = content.replace(old_pop, new_pop)

with open(RUN_PY, 'w') as f:
    f.write(content)

print('Patched run.py: model persistence enabled')
PYEOF
fi

# Also delete pyc cache
find "$HERMES_AGENT" -name 'model_switch.cpython*.pyc' -delete 2>/dev/null || true
find "$HERMES_AGENT" -path '*__pycache__/model_switch*' -delete 2>/dev/null || true

echo "Done. Restart hermes-gateway to apply."
