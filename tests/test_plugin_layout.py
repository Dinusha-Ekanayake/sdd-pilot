"""What the plugin directory checks: literal hook paths, no bin/, a valid icon."""

import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = re.compile(r"^\$\{CLAUDE_PLUGIN_ROOT\}/(scripts/[\w./-]+\.sh)$")


def _hooks() -> list[dict[str, object]]:
    data = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return [hook for groups in data["hooks"].values() for g in groups for hook in g["hooks"]]


def test_every_hook_runs_a_literal_shell_script_in_exec_form() -> None:
    hooks = _hooks()
    assert hooks
    for hook in hooks:
        assert hook["command"] == "bash", hook  # exec form: no shell parses the line
        args = hook["args"]
        assert isinstance(args, list) and len(args) == 2, hook
        script = HOOK_SCRIPT.match(str(args[0]))
        assert script, f"path must be spelled literally from the plugin root: {args[0]}"
        assert (ROOT / script.group(1)).is_file()
        assert str(args[1]).startswith("hook-")


def test_no_bin_folder() -> None:
    # Claude Code puts bin/ on PATH, and claude.ai and Cowork refuse plugins that have it.
    assert not (ROOT / "bin").exists()


def test_icon_is_a_square_png_of_an_accepted_size() -> None:
    data = (ROOT / ".claude-plugin" / "icon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) < 2 * 1024 * 1024
    width, height = struct.unpack(">II", data[16:24])
    assert width == height and 512 <= width <= 2048
