"""A short brief per task group, so a subagent reads one small file instead of the spec."""

import ast
import re
import shutil
import subprocess
from pathlib import Path

from sdd_pilot.config import Config
from sdd_pilot.tasks import Task, parse_tasks

BRIEF_DIR = Path(".sdd") / "briefs"
GRAPHIFY_BUDGET = 400
_BACKTICKED = re.compile(r"`([^`]+)`")
_REQ_OR_AC = re.compile(r"^- (?:\[[ x]\] )?(?:REQ|AC)-")
_JS_EXPORT = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|interface|type)\s+\w+[^{=]*"
)

RULES = """\
## Rules
- TDD: write the failing test, run it (RED), implement (GREEN), refactor.
- Open only the files named here. If you must look further, use `graphify query "..."`
  when the project has a graph, and say so under BRIEF GAPS in your report.
- Gate: `{sdd} check` must print `SDD CHECK: PASS`.
- Never commit, push, delete data or install packages.
- If the spec is ambiguous and the choice changes behaviour, stop and report it under
  QUESTIONS instead of guessing. Record smaller choices under ASSUMPTIONS.

## Report (return exactly this, nothing else)
STATUS: done | blocked
TASKS: <ids>
FILES: <changed files>
TESTS: <new test names, one line>
CHECK: <the SDD CHECK line and coverage line>
ASSUMPTIONS: <bullets or none>
QUESTIONS: <bullets or none>
BRIEF GAPS: <what was missing from this brief, or none>
"""


def _is_specific(part: str) -> bool:
    """Module paths, snake_case and CamelCase names; plain words match too many lines."""
    return "/" in part or "_" in part or re.search(r"[a-z][A-Z]", part) is not None


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for item in _BACKTICKED.findall(text):
        tokens.add(item)
        tokens.update(part for part in re.split(r"[.:\s]", item) if _is_specific(part))
        # `pkg.func` usually points at a file named pkg.<ext> in the plan.
        module, dot, _ = item.partition(".")
        if dot and module.isidentifier() and "/" not in item:
            tokens.add(f"/{module}.")
    return tokens


def _matching_lines(path: Path, tokens: set[str]) -> list[str]:
    if not path.exists() or not tokens:
        return []
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if any(token in line for token in tokens)
    ]


def signatures(path: Path) -> list[str]:
    """Public top-level names: Python via ast, JS/TS via ``export`` lines."""
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".py":
        return [m.group(0).strip() for line in text.splitlines() if (m := _JS_EXPORT.match(line))]
    out = []
    for node in ast.parse(text).body:
        if not isinstance(node, ast.FunctionDef | ast.ClassDef) or node.name.startswith("_"):
            continue
        if isinstance(node, ast.FunctionDef):
            ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            head = f"def {node.name}({ast.unparse(node.args)}){ret}"
        else:
            head = f"class {node.name}"
        doc = (ast.get_docstring(node) or "").split("\n")[0]
        out.append(f"{head}  # {doc}" if doc else head)
    return out


def _graphify(root: Path, query: str) -> str:
    exe = shutil.which("graphify")
    if exe is None or not (root / "graphify-out").exists() or not query:
        return ""
    try:
        proc = subprocess.run(
            [exe, "query", query, "--budget", str(GRAPHIFY_BUDGET)],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return "\n".join(line for line in proc.stdout.splitlines() if line.startswith("NODE"))


def _api_section(cfg: Config, plan_lines: list[str]) -> list[str]:
    roots = "|".join(re.escape(r) for r in cfg.path_roots)
    path_re = re.compile(rf"(?:{roots})/[\w/.-]+\.\w+")
    named = set(path_re.findall("\n".join(plan_lines)))
    # A new module should reuse what its package already has, so show its siblings too.
    siblings = {
        sibling.relative_to(cfg.root).as_posix()
        for rel in named
        if not (cfg.root / rel).exists() and (cfg.root / rel).parent.is_dir()
        for sibling in (cfg.root / rel).parent.glob(f"*{Path(rel).suffix}")
        if not sibling.name.startswith("__init__")
    }
    apis = []
    for rel in sorted(named | siblings | set(cfg.helper_files)):
        path = cfg.root / rel
        if not path.exists():
            apis.append(f"### {rel}\n(new file)")
        elif path.suffix in (".py", ".ts", ".tsx", ".js", ".mjs"):
            apis.append(f"### {rel}\n" + "\n".join(signatures(path) or ["(no public names)"]))
    return apis


def build_brief(cfg: Config, spec_dir: Path, task_ids: list[str], sdd: str = "sdd") -> str:
    tasks = {t.id: t for t in parse_tasks(spec_dir / "tasks.md")}
    missing = [i for i in task_ids if i not in tasks]
    if missing:
        raise ValueError(f"unknown tasks: {missing}")
    chosen: list[Task] = [tasks[i] for i in task_ids]
    tokens = set().union(*(_tokens(f"{t.text} {t.test}") for t in chosen))
    plan_lines = _matching_lines(spec_dir / "plan.md", tokens)
    spec_lines = (spec_dir / "spec.md").read_text(encoding="utf-8").splitlines()
    requirements = [line for line in spec_lines if _REQ_OR_AC.match(line)]

    risk = chosen[0].risk
    rows = "\n".join(f"| {t.id} | {t.text} | {t.test} | {t.risk} |" for t in chosen)
    parts = [
        f"# Brief: {', '.join(task_ids)} ({spec_dir.name})",
        f"Risk: {risk}. Reviewer model: {cfg.models[risk]}.",
        "## Tasks\n| ID | Task | Test | Risk |\n|---|---|---|---|\n" + rows,
        "## Plan lines\n" + ("\n".join(plan_lines) or "(none matched)"),
        "## Requirements and acceptance criteria\n" + ("\n".join(requirements) or "(none)"),
        "## Existing APIs (signatures only)\n" + ("\n\n".join(_api_section(cfg, plan_lines))),
    ]
    if cfg.graphify:
        query = " ".join(sorted(t for t in tokens if "/" not in t and " " not in t)[:8])
        nodes = _graphify(cfg.root, query)
        if nodes:
            parts.append("## Related graph nodes\n" + nodes)
    parts.append(RULES.format(sdd=sdd))
    return "\n\n".join(parts) + "\n"


def write_brief(cfg: Config, spec_dir: Path, task_ids: list[str], sdd: str = "sdd") -> Path:
    path = cfg.root / BRIEF_DIR / f"{task_ids[0]}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_brief(cfg, spec_dir, task_ids, sdd), encoding="utf-8")
    return path
