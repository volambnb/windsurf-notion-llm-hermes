#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "=== Applying Super Kaka persona to Hermes ==="

# 1. Copy SOUL.md
cp "$SCRIPT_DIR/../config/SOUL.md" "$HERMES_HOME/SOUL.md"
echo "[1/4] SOUL.md updated"

# 2. Copy USER.md (memory)
mkdir -p "$HERMES_HOME/memories"
cp "$SCRIPT_DIR/../config/USER.md" "$HERMES_HOME/memories/USER.md"
echo "[2/4] USER.md (memories) updated"

# 3. Install skill
SKILL_DIR="$HERMES_HOME/skills/communication/super-kaka-operating-rules"
mkdir -p "$SKILL_DIR"
cp "$SCRIPT_DIR/../config/super-kaka-operating-rules-SKILL.md" "$SKILL_DIR/SKILL.md"
echo "[3/4] Skill installed at $SKILL_DIR/SKILL.md"

# 4. Restart gateway
if systemctl is-active hermes-gateway >/dev/null 2>&1; then
  systemctl restart hermes-gateway
  echo "[4/4] hermes-gateway restarted"
else
  echo "[4/4] hermes-gateway not running (skip restart)"
fi

echo ""
echo "=== Done ==="
