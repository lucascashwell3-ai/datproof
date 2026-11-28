"""The install command names one fixed commit everywhere, and that commit exists.

Every copy of `uvx --from git+https://github.com/lucascashwell3-ai/datproof...` in the tracked files
must carry `@<SERVER_PIN>` from datproof_feed/pages.py, the one place the pin lives."""
import pathlib
import re
import subprocess

import pytest

from datproof_feed import pages

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_URL = re.compile(r"git\+https://github\.com/lucascashwell3-ai/datproof(?:\.git)?(@[0-9A-Za-z._/-]+)?")
SKIP = ("archive/", "tests/", "datproof_feed/pages.py")  # retired concept; tests quoting it; the pin itself


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _tracked() -> list[pathlib.Path]:
    out = _git("ls-files")
    if out.returncode == 0:
        names = out.stdout.splitlines()
    else:  # git not runnable here: every file outside .git
        names = [str(f.relative_to(ROOT)) for f in ROOT.rglob("*") if f.is_file() and ".git" not in f.parts]
    return [ROOT / f for f in names if not f.startswith(SKIP)]


def unpinned(text: str) -> list[str]:
    """Every install address in `text` that does not name SERVER_PIN."""
    return [m.group(0) for m in REPO_URL.finditer(text) if m.group(1) != "@" + pages.SERVER_PIN]


def test_pin_is_a_full_commit():
    assert re.fullmatch(r"[0-9a-f]{40}", pages.SERVER_PIN)
    assert pages.INSTALL_FROM.endswith("@" + pages.SERVER_PIN)
    assert pages.INSTALL_FROM in pages.SETUP


def test_every_copy_names_the_pin():
    found, bad = 0, []
    for f in _tracked():
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        found += len(REPO_URL.findall(text))
        bad += [f"{f.relative_to(ROOT)}: {u}" for u in unpinned(text)]
    assert found >= 6, f"expected the install command in README, the page, index.md and llms.txt; found {found}"
    assert not bad, "install command not pinned to SERVER_PIN:\n" + "\n".join(bad)


def test_planted_unpinned_copy_is_caught():
    pin = pages.SERVER_PIN
    assert unpinned(f"uvx --from git+https://github.com/lucascashwell3-ai/datproof@{pin} datproof-mcp") == []
    assert unpinned("uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp")
    assert unpinned('"git+https://github.com/lucascashwell3-ai/datproof@main"')
    assert unpinned(f"git+https://github.com/lucascashwell3-ai/datproof@{'0' * 40}")


def test_pinned_commit_exists():
    if _git("--version").returncode != 0:
        pytest.skip("git not runnable here")
    if _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        pytest.skip("shallow clone: history not here to check")
    r = _git("cat-file", "-e", pages.SERVER_PIN + "^{commit}")
    assert r.returncode == 0, f"SERVER_PIN {pages.SERVER_PIN} is not a commit in this repository"
