#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_ROOT="${PATCH_ROOT:-$REPO_ROOT/patches/hermes-1.7-live}"
HERMES_ROOT="${HERMES_ROOT:-/opt/hermes-agent}"
HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
ts="$(date +%Y%m%d_%H%M%S)"

echo "=== Hermes 1.7 self-heal router ==="
echo "Patch root:  $PATCH_ROOT"
echo "Hermes root: $HERMES_ROOT"
echo "Hermes home: $HERMES_HOME"

HPF_SRC="$PATCH_ROOT/opt/hermes-agent/gateway_ext/hermes_windsurf_fallback/hpf_gateway"
HPF_DST="$HERMES_ROOT/gateway_ext/hermes_windsurf_fallback/hpf_gateway"
if [ ! -f "$HPF_SRC/self_heal_router.py" ]; then
  echo "ERROR: self_heal_router.py not found in patch root" >&2
  exit 1
fi

mkdir -p "$HPF_DST"
if [ -f "$HPF_DST/self_heal_router.py" ]; then
  cp "$HPF_DST/self_heal_router.py" "$HPF_DST/self_heal_router.py.bak.selfheal-$ts"
fi
cp "$HPF_SRC/self_heal_router.py" "$HPF_DST/self_heal_router.py"

python3 - "$HERMES_ROOT" <<'PY'
from __future__ import annotations

from pathlib import Path
import shutil
import sys
import time

root = Path(sys.argv[1])
ts = time.strftime("%Y%m%d_%H%M%S")

def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + f".bak.selfheal-{ts}"))

def patch_once(path: Path, needle: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    if needle not in text:
        raise SystemExit(f"anchor not found in {path}: {needle[:80]!r}")
    backup(path)
    path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")

base = root / "tools/environments/base.py"
terminal = root / "tools/terminal_tool.py"
chat = root / "agent/chat_completion_helpers.py"

base_text = base.read_text(encoding="utf-8")
if "_normalize_path_exports" not in base_text:
    needle = '''def _file_mtime_key(host_path: str) -> tuple[float, int] | None:
    """Return ``(mtime, size)`` for cache comparison, or ``None`` if unreadable."""
    try:
        st = Path(host_path).stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


'''
    replacement = needle + '''def _normalize_path_exports(command: str) -> str:
    """Route PATH export normalization through self-heal router when available."""
    try:
        from hpf_gateway.self_heal_router import normalize_path_exports
        return normalize_path_exports(command)
    except Exception:
        if "export PATH=" not in command:
            return command
        sane = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        out = []
        for line in command.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("export PATH=") and "/usr/bin" not in stripped:
                line = f"{line}:${{PATH:-{sane}}}:{sane}"
            out.append(line)
        return "\\n".join(out)


'''
    patch_once(base, needle, replacement)

patch_once(
    base,
    '''        exec_command, sudo_stdin = self._prepare_command(command)
        # Guard against the `A && B &` subshell-wait trap by default.
''',
    '''        exec_command, sudo_stdin = self._prepare_command(command)
        exec_command = _normalize_path_exports(exec_command)
        # Guard against the `A && B &` subshell-wait trap by default.
''',
)

patch_once(
    terminal,
    '''        if not isinstance(command, str):
            logger.warning(
                "Rejected invalid terminal command value: %s",
                type(command).__name__,
            )
            return json.dumps({
''',
    '''        if not isinstance(command, str):
            logger.warning(
                "Rejected invalid terminal command value: %s",
                type(command).__name__,
            )
            try:
                from hpf_gateway.self_heal_router import record_event
                record_event(
                    {"type": "tool_call_malformed", "tool": "terminal", "arg_type": type(command).__name__}
                )
            except Exception:
                pass
            return json.dumps({
''',
)

patch_once(
    chat,
    '''                logger.warning(
                    "Partial stream dropped tool call(s) %s after %s chars "
                    "of text; surfaced warning to user: %s",
                    _partial_names, len(_partial_text or ""), result["error"],
                )
''',
    '''                logger.warning(
                    "Partial stream dropped tool call(s) %s after %s chars "
                    "of text; surfaced warning to user: %s",
                    _partial_names, len(_partial_text or ""), result["error"],
                )
                try:
                    from hpf_gateway.self_heal_router import record_event
                    _decision = record_event(
                        {
                            "type": "stream_stall",
                            "partial_tool_names": _partial_names,
                            "text_chars": len(_partial_text or ""),
                            "error": str(result["error"]),
                        }
                    )
                    if getattr(_decision, "resume_from_checkpoint", False):
                        _partial_text = (_partial_text or "") + "\\nSelf-heal checkpoint saved; retry will resume same model from checkpoint."
                except Exception:
                    pass
''',
)
PY

PYTHONPATH="$HERMES_ROOT/gateway_ext/hermes_windsurf_fallback" python3 - <<'PY'
from hpf_gateway.self_heal_router import self_test, normalize_path_exports
result = self_test()
assert result["provider_timeout"]["retry_same_model"] is True
assert result["tool_call_malformed"]["resume_from_checkpoint"] is True
assert result["csrf_auth"]["actions"][0] == "restart_windsurf_clean"
assert "/usr/bin" in normalize_path_exports("export PATH=/usr/local/go/bin\nls")
print("self-heal dry-run OK")
PY

python3 -m py_compile \
  "$HPF_DST/self_heal_router.py" \
  "$HERMES_ROOT/tools/environments/base.py" \
  "$HERMES_ROOT/tools/terminal_tool.py" \
  "$HERMES_ROOT/agent/chat_completion_helpers.py"

if command -v systemctl >/dev/null 2>&1; then
  systemctl restart hermes-gateway.service || true
fi

echo "Done. Backups use suffix: .bak.selfheal-$ts"
