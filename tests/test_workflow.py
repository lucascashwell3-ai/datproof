"""The daily workflow: publish retries and a live-date check, nothing heavy in the published folder."""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"


def grid() -> dict:
    return yaml.safe_load((WF / "grid.yml").read_text())


def deploy_steps(doc: dict) -> list[dict]:
    return doc["jobs"]["deploy"]["steps"]


def check_deploy(doc: dict) -> list[str]:
    """What is wrong with the deploy job, in words; empty when it retries and checks the live date."""
    bad = []
    steps = deploy_steps(doc)
    deploys = [s for s in steps if str(s.get("uses", "")).startswith("actions/deploy-pages")]
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-pages-artifact")]
    if len(deploys) < 3 or len(uploads) != len(deploys):
        bad.append(f"{len(deploys)} deploy tries and {len(uploads)} uploads; want 3 of each")
    for prev, nxt in zip(deploys, deploys[1:]):
        if f"steps.{prev.get('id')}.outcome == 'failure'" not in str(nxt.get("if", "")):
            bad.append(f"{nxt.get('id')} does not run only after {prev.get('id')} failed")
        if not prev.get("continue-on-error"):
            bad.append(f"{prev.get('id')} stops the job instead of letting the next try run")
    clears = [s for s in steps if "actions/artifacts/" in str(s.get("run", "")) and "DELETE" in str(s.get("run", ""))]
    if len(clears) < len(deploys):
        bad.append("an earlier upload is not cleared before each try")
    built = next((s for s in steps if s.get("id") == "built"), {})
    if "site/index.html" not in str(built.get("run", "")) or "status.json" not in str(built.get("run", "")):
        bad.append("the live dates must be compared with the checked-out home page and status.json")
    live = [s for s in steps if "curl" in str(s.get("run", "")) and "status.json" in str(s.get("run", "")) and "dateModified" in str(s.get("run", ""))]
    if not live:
        bad.append("no check that the live home page and status.json show the date just built")
    elif "exit 1" not in live[0]["run"] or "?run=" not in live[0]["run"]:
        bad.append("the live-date check must skip caches and fail the run")
    if "actions: write" not in yaml.safe_dump(doc["jobs"]["deploy"].get("permissions", {})).replace("'", ""):
        bad.append("deploy job cannot delete its earlier upload (needs actions: write)")
    return bad


def test_deploy_retries_and_checks_the_live_date():
    assert check_deploy(grid()) == []


def test_planted_single_try_deploy_is_caught():
    doc = grid()
    steps = deploy_steps(doc)
    doc["jobs"]["deploy"]["steps"] = [s for s in steps if s.get("id") not in ("deploy2", "deploy3")
                                      and "try 2" not in str(s.get("name")) and "try 3" not in str(s.get("name"))]
    assert check_deploy(doc)


def test_planted_missing_live_check_is_caught():
    doc = grid()
    doc["jobs"]["deploy"]["steps"] = [s for s in deploy_steps(doc) if "dateModified" not in str(s.get("run", ""))]
    assert any("live" in b for b in check_deploy(doc))


def test_deploy_and_live_check_run_on_main_only():
    doc = grid()
    assert doc["jobs"]["deploy"]["if"] == "needs.build.outputs.dry_run != 'true'"
    step = next(s for s in doc["jobs"]["build"]["steps"] if s.get("id") == "dry-run")
    assert 'github.ref }}" != "refs/heads/main"' in step["run"]


def test_published_folder_carries_no_screenshots():
    assert not (ROOT / "site" / "screens").exists(), "screenshots belong in docs/screens, not the published site"
    big = [p for p in (ROOT / "site").rglob("*") if p.is_file() and p.stat().st_size > 1_500_000]
    assert not big, f"files over 1.5 MB in the published folder: {big}"


def test_only_the_daily_workflow_can_publish():
    """The earlier product's workflow rebuilt site/index.html and deployed it; it lives in archive/ now."""
    assert not (WF / "daily-brief.yml").exists()
    assert (ROOT / "archive" / "workflows" / "daily-brief.yml").exists()
    publishers = [p.name for p in WF.glob("*.y*ml") if "deploy-pages" in p.read_text()]
    assert publishers == ["grid.yml"], publishers


def test_every_action_is_pinned_to_a_commit_with_its_version():
    import re
    for f in WF.glob("*.y*ml"):
        for line in f.read_text().splitlines():
            m = re.search(r"uses:\s*(\S+)(.*)", line)
            if not m or m.group(1).startswith("./"):
                continue
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)), f"{f.name}: {line.strip()}"
            assert re.search(r"#\s*v\d", m.group(2)), f"{f.name}: no version comment: {line.strip()}"


def test_each_job_asks_for_the_least_it_needs():
    doc = grid()
    assert doc["permissions"] == {"contents": "read"}
    jobs = doc["jobs"]
    assert jobs["build"]["permissions"] == {"contents": "write"}
    assert jobs["feed-check"]["permissions"] == {}
    assert jobs["deploy"]["permissions"] == {"contents": "read", "pages": "write", "id-token": "write", "actions": "write"}


def test_planted_unpinned_action_is_caught(tmp_path):
    import re
    line = "      - uses: actions/checkout@v4"
    m = re.search(r"uses:\s*(\S+)(.*)", line)
    assert not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1))


def test_security_policy_is_linked_from_the_foot():
    assert (ROOT / "SECURITY.md").exists()
    assert len((ROOT / "SECURITY.md").read_text().strip().splitlines()) <= 8
    foot = (ROOT / "site" / "index.html").read_text().split('<footer', 1)[1]
    assert "/security/policy" in foot
