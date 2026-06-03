#!/bin/bash
set -euo pipefail

NOTION2API_ROOT="${NOTION2API_ROOT:-/opt/notion2api}"
HERMES_CONFIG="${HERMES_CONFIG:-/root/.hermes/config.yaml}"
ts="$(date +%Y%m%d_%H%M%S)"

echo "=== Notion Opus 4.8 mapping update ==="
echo "Notion2API root: $NOTION2API_ROOT"
echo "Hermes config:    $HERMES_CONFIG"

python3 - "$NOTION2API_ROOT" "$HERMES_CONFIG" "$ts" <<'PY'
from __future__ import annotations

from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
hermes_config = Path(sys.argv[2])
ts = sys.argv[3]


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + f".bak.opus48-{ts}"))


registry = root / "app/model_registry.py"
if registry.exists():
    backup(registry)
    text = registry.read_text(encoding="utf-8")
    if '"claude-opus4.8"' not in text:
        text = text.replace(
            '    "claude-opus4.7": "apricot-sorbet-high",\n',
            '    "claude-opus4.7": "apricot-sorbet-high",\n'
            '    "claude-opus4.8": "ambrosia-tart-high",\n',
        )
        text = text.replace(
            '    "claude-opus4.7": "Claude Opus 4.7",\n',
            '    "claude-opus4.7": "Claude Opus 4.7",\n'
            '    "claude-opus4.8": "Claude Opus 4.8",\n',
        )
        text = text.replace(
            '    "claude-opus4.7": "✳️",\n',
            '    "claude-opus4.7": "✳️",\n'
            '    "claude-opus4.8": "✳️",\n',
        )
    registry.write_text(text, encoding="utf-8")

schemas = root / "app/schemas.py"
if schemas.exists():
    backup(schemas)
    text = schemas.read_text(encoding="utf-8")
    text = text.replace('default="claude-opus4.6"', 'default="claude-opus4.8"')
    schemas.write_text(text, encoding="utf-8")

if hermes_config.exists():
    backup(hermes_config)
    try:
        import yaml
        data = yaml.safe_load(hermes_config.read_text(encoding="utf-8"))
        notion = data.setdefault("providers", {}).setdefault("notion-proxy", {})
        notion["default_model"] = "claude-opus4.8"
        models = list(notion.get("models") or [])
        if "claude-opus4.8" not in models:
            idx = models.index("claude-opus4.7") + 1 if "claude-opus4.7" in models else len(models)
            models.insert(idx, "claude-opus4.8")
        notion["models"] = models
        data.setdefault("tier_models", {})["advisor"] = "opus-4.8"
        hermes_config.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except Exception:
        text = hermes_config.read_text(encoding="utf-8")
        text = text.replace("default_model: claude-sonnet4.6", "default_model: claude-opus4.8")
        text = text.replace("default_model: claude-opus4.7", "default_model: claude-opus4.8")
        if "- claude-opus4.8" not in text:
            text = text.replace("- claude-opus4.7\n", "- claude-opus4.7\n    - claude-opus4.8\n", 1)
        text = text.replace("advisor: opus-4.7", "advisor: opus-4.8")
        hermes_config.write_text(text, encoding="utf-8")
PY

python3 -m py_compile \
  "$NOTION2API_ROOT/app/model_registry.py" \
  "$NOTION2API_ROOT/app/schemas.py"

if command -v systemctl >/dev/null 2>&1; then
  systemctl restart notion2api.service || true
  systemctl restart hermes-gateway.service || true
fi

echo "Done. Mapping: claude-opus4.8 -> ambrosia-tart-high"
