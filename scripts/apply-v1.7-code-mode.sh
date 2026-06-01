#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_ROOT="${PATCH_ROOT:-$REPO_ROOT/patches/hermes-1.7-live}"
HERMES_ROOT="${HERMES_ROOT:-/opt/hermes-agent}"
HERMES_HOME="${HERMES_HOME:-/root/.hermes}"

ts="$(date +%Y%m%d_%H%M%S)"

echo "=== Hermes 1.7 /code plan-first project isolation ==="
echo "Patch root:  $PATCH_ROOT"
echo "Hermes root: $HERMES_ROOT"
echo "Hermes home: $HERMES_HOME"

if [ ! -d "$PATCH_ROOT" ]; then
  echo "ERROR: patch root not found: $PATCH_ROOT" >&2
  exit 1
fi

copy_with_backup() {
  local src="$1"
  local dst="$2"
  if [ ! -f "$src" ]; then
    echo "ERROR: patch file not found: $src" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dst")"
  if [ -f "$dst" ]; then
    cp "$dst" "$dst.bak.v1.7-code-$ts"
  fi
  cp "$src" "$dst"
  echo "Applied: $dst"
}

copy_with_backup "$PATCH_ROOT/root/.hermes/plugins/plan-first-router/__init__.py" \
  "$HERMES_HOME/plugins/plan-first-router/__init__.py"
copy_with_backup "$PATCH_ROOT/opt/hermes-agent/gateway_ext/hermes_windsurf_fallback/hpf_gateway/plan_pipeline.py" \
  "$HERMES_ROOT/gateway_ext/hermes_windsurf_fallback/hpf_gateway/plan_pipeline.py"
copy_with_backup "$PATCH_ROOT/opt/hermes-agent/hermes_cli/commands.py" \
  "$HERMES_ROOT/hermes_cli/commands.py"
copy_with_backup "$PATCH_ROOT/opt/hermes-agent/gateway/run.py" \
  "$HERMES_ROOT/gateway/run.py"
copy_with_backup "$PATCH_ROOT/opt/hermes-agent/tools/file_tools.py" \
  "$HERMES_ROOT/tools/file_tools.py"

python3 -m py_compile \
  "$HERMES_HOME/plugins/plan-first-router/__init__.py" \
  "$HERMES_ROOT/gateway_ext/hermes_windsurf_fallback/hpf_gateway/plan_pipeline.py" \
  "$HERMES_ROOT/hermes_cli/commands.py" \
  "$HERMES_ROOT/gateway/run.py" \
  "$HERMES_ROOT/tools/file_tools.py"

grep -q "SMART_TECHNICAL_POLICY" "$HERMES_HOME/plugins/plan-first-router/__init__.py"
grep -q "Project Folder:" "$HERMES_HOME/plugins/plan-first-router/__init__.py"
grep -q "stale plan denied" "$HERMES_ROOT/tools/file_tools.py"
grep -q "CommandDef(\"code\"" "$HERMES_ROOT/hermes_cli/commands.py"

if command -v systemctl >/dev/null 2>&1; then
  echo "Restarting hermes-gateway.service..."
  systemctl restart hermes-gateway.service || true
fi

echo "Done. Backups use suffix: .bak.v1.7-code-$ts"
