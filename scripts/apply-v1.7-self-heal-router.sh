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
path_helper = '''def _normalize_path_exports(command: str) -> str:
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
if "_normalize_path_exports" not in base_text:
    needle = '''def _file_mtime_key(host_path: str) -> tuple[float, int] | None:
    """Return ``(mtime, size)`` for cache comparison, or ``None`` if unreadable."""
    try:
        st = Path(host_path).stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


'''
    replacement = needle + path_helper + "\n"
    patch_once(base, needle, replacement)
else:
    start = base_text.find("def _normalize_path_exports(command: str) -> str:")
    end = base_text.find("\n\n# ---------------------------------------------------------------------------", start)
    if start != -1 and end != -1 and "hpf_gateway.self_heal_router" not in base_text[start:end]:
        backup(base)
        base.write_text(base_text[:start] + path_helper + base_text[end:], encoding="utf-8")

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

todo = root / "tools/todo_tool.py"
todo_text = todo.read_text(encoding="utf-8")
if "def _coerce_item(item: Any, index: int) -> Dict[str, Any]:" not in todo_text:
    backup(todo)
    todo_text = todo_text.replace(
        '''    @staticmethod
    def _validate(item: Dict[str, Any]) -> Dict[str, str]:
''',
        '''    @staticmethod
    def _coerce_item(item: Any, index: int) -> Dict[str, Any]:
        """Accept imperfect model output instead of crashing the agent loop."""
        if isinstance(item, dict):
            return item
        content = str(item).strip() if item is not None else ""
        return {"id": f"T{index + 1}", "content": content or "(no description)", "status": "pending"}

    @staticmethod
    def _validate(item: Dict[str, Any]) -> Dict[str, str]:
''',
    )
    todo_text = todo_text.replace(
        '''        if not merge:
            # Replace mode: new list entirely
            self._items = [self._validate(t) for t in self._dedupe_by_id(todos)]
        else:
            # Merge mode: update existing items by id, append new ones
            existing = {item["id"]: item for item in self._items}
            for t in self._dedupe_by_id(todos):
''',
        '''        normalized = [self._coerce_item(t, i) for i, t in enumerate(todos or [])]
        if not merge:
            # Replace mode: new list entirely
            self._items = [self._validate(t) for t in self._dedupe_by_id(normalized)]
        else:
            # Merge mode: update existing items by id, append new ones
            existing = {item["id"]: item for item in self._items}
            for t in self._dedupe_by_id(normalized):
''',
    )
    todo_text = todo_text.replace(
        '''        for i, item in enumerate(todos):
            item_id = str(item.get("id", "")).strip() or "?"
            last_index[item_id] = i
        return [todos[i] for i in sorted(last_index.values())]
''',
        '''        for i, item in enumerate(todos or []):
            if not isinstance(item, dict):
                item = TodoStore._coerce_item(item, i)
                todos[i] = item
            item_id = str(item.get("id", "")).strip() or "?"
            last_index[item_id] = i
        return [todos[i] for i in sorted(last_index.values())]
''',
    )
    todo.write_text(todo_text, encoding="utf-8")

windsurf_tool_emulation = Path("/opt/WindsurfAPI/src/handlers/tool-emulation.js")
if windsurf_tool_emulation.exists():
    js = windsurf_tool_emulation.read_text(encoding="utf-8")
    changed = False
    if "function parseParameterStyleToolCallBody(body)" not in js:
        marker = "function parseGlm47ToolCallBody(body) {\n"
        helper = r'''function parseParameterStyleToolCallBody(body) {
  if (typeof body !== 'string' || !body.includes('<parameter')) return null;
  const params = {};
  let name = null;
  const attrName = body.match(/<tool_call\b[^>]*\bname\s*=\s*["']([^"']+)["'][^>]*>/i);
  if (attrName) name = attrName[1];
  const re = /<parameter\b([^>]*)>([\s\S]*?)<\/parameter>/gi;
  let m;
  while ((m = re.exec(body)) !== null) {
    const attrs = m[1] || '';
    const keyMatch = attrs.match(/\bname\s*=\s*["']([^"']+)["']/i);
    if (!keyMatch) continue;
    const key = keyMatch[1];
    let value = (m[2] || '').trim();
    if (/\bstring\s*=\s*["']false["']/i.test(attrs)) {
      const lowered = value.toLowerCase();
      if (lowered === 'true') value = true;
      else if (lowered === 'false') value = false;
      else if (/^-?\d+(?:\.\d+)?$/.test(value)) value = Number(value);
    }
    params[key] = value;
  }
  if (!Object.keys(params).length) return null;
  if (!name) {
    if ('command' in params) name = 'terminal';
    else if ('path' in params || 'file_path' in params) name = 'read_file';
    else name = 'terminal';
  }
  return { name, argumentsJson: JSON.stringify(params) };
}

'''
        if marker not in js:
            raise SystemExit("Windsurf tool-emulation parseGlm47 anchor missing")
        js = js.replace(marker, helper + marker, 1)
        changed = True
    if "parameter_xml" not in js:
        marker = "  // 1. Markdown-fenced JSON. Tolerate ```json, ```tool_call, or bare ```.\n"
        parameter_salvage = r'''  working = working.replace(/<tool_call\b[^>]*>[\s\S]*?<\/tool_call>/gi, (match) => {
    const tc = parseParameterStyleToolCallBody(match);
    if (!tc) return match;
    calls.push({ id: newId(), ...tc });
    formats.add('parameter_xml');
    return '';
  });
  working = working.replace(/<\/?tool_calls?>/gi, '');

'''
        if marker not in js:
            raise SystemExit("Windsurf tool-emulation salvage anchor missing")
        js = js.replace(marker, parameter_salvage + marker, 1)
        changed = True
    old_flush = '''    if (this.inToolCall) {
      this.inToolCall = false;
      return { text: `<tool_call>${remaining}`, toolCalls: [] };
    }
'''
    new_flush = '''    if (this.inToolCall) {
      this.inToolCall = false;
      const parameterCall = parseParameterStyleToolCallBody(`<tool_call>${remaining}`);
      if (parameterCall) {
        parameterCall.id = `call_param_${this._totalSeen}_${Date.now().toString(36)}`;
        this._totalSeen++;
        return { text: '', toolCalls: [parameterCall] };
      }
      return { text: `<tool_call>${remaining}`, toolCalls: [] };
    }
'''
    if old_flush in js and new_flush not in js:
        js = js.replace(old_flush, new_flush, 1)
        changed = True
    if "\x08" in js:
        js = js.replace("\x08", r"\b")
        changed = True
    if changed:
        backup(windsurf_tool_emulation)
        windsurf_tool_emulation.write_text(js, encoding="utf-8")

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
  "$HERMES_ROOT/tools/todo_tool.py" \
  "$HERMES_ROOT/agent/chat_completion_helpers.py"

if [ -f /opt/WindsurfAPI/src/handlers/tool-emulation.js ] && command -v node >/dev/null 2>&1; then
  node --check /opt/WindsurfAPI/src/handlers/tool-emulation.js
  systemctl restart windsurf-api.service || true
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl restart hermes-gateway.service || true
fi

echo "Done. Backups use suffix: .bak.selfheal-$ts"
