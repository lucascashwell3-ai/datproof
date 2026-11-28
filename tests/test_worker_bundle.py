"""The Cloudflare Worker's build copies every module the web entry needs, and its entry stays thin."""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "datproof_feed"
WRANGLER = (ROOT / "worker" / "wrangler.toml").read_text()


def needed(start: str = "web") -> set[str]:
    """datproof_feed modules reached by imports from `start`, itself included."""
    seen, todo = set(), [start]
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        for node in ast.walk(ast.parse((PKG / f"{mod}.py").read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "datproof_feed":
                todo += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("datproof_feed."):
                todo.append(node.module.split(".", 1)[1])
            elif isinstance(node, ast.Import):
                todo += [a.name.split(".", 1)[1] for a in node.names if a.name.startswith("datproof_feed.")]
    return seen


def copied(toml: str = WRANGLER) -> set[str]:
    command = re.search(r'^command = "(.*)"$', toml, re.M).group(1)
    return set(re.findall(r"\.\./datproof_feed/(\w+)\.py", command))


def missing(toml: str = WRANGLER) -> set[str]:
    return (needed() | {"__init__"}) - copied(toml)


def test_build_copies_every_needed_module():
    assert needed() == {"web", "server", "compare", "scenarios"}
    assert not missing()


def test_planted_missing_module_is_caught():
    assert missing(WRANGLER.replace("../datproof_feed/scenarios.py ", "")) == {"scenarios"}


def test_worker_settings_and_entry():
    assert re.search(r'compatibility_flags = \["python_workers", "disable_python_external_sdk"\]', WRANGLER)
    assert 'main = "src/entry.py"' in WRANGLER
    entry = (ROOT / "worker" / "src" / "entry.py").read_text()
    assert "web.respond(" in entry and "server.fetch_bytes = platform_get" in entry
    assert "def call_tool" not in entry and "TOOLS" not in entry  # one implementation of the tools
