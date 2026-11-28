"""/grid/ is frozen: published as last built, with a line saying so; the daily job no longer runs the
filings pull, the ticker or the grid build, and nothing the home page or the feed is built from needs them."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

import pytest

from scripts import run_status

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = (ROOT / ".github" / "workflows" / "grid.yml").read_text()
GRID_ONLY = ("scripts/pull_mstr.py", "scripts/pull_asst.py", "scripts/pull_metaplanet.py",
             "scripts/fetch_ticker.py", "scripts/build_grid_site.py")
KEPT = ("scripts/fetch_credit.py", "datproof_feed.backing", "datproof_feed.rates", "datproof_feed.brokers",
        "datproof_feed.build", "datproof_feed.pages", "datproof_feed.og")


def run_lines(wf: str) -> str:
    """The workflow's text without comment lines, so a step named in a comment does not count."""
    return "\n".join(ln for ln in wf.splitlines() if not ln.lstrip().startswith("#"))


def grid_steps_left(wf: str) -> list[str]:
    body = run_lines(wf)
    return [s for s in GRID_ONLY if s in body]


def test_daily_job_runs_no_grid_only_step():
    assert grid_steps_left(WF) == []
    for step in KEPT:
        assert step in run_lines(WF), step


def test_planted_grid_step_is_caught():
    planted = WF.replace("      - name: Credit feeds", "      - name: Build grid page (/grid/)\n"
                         "        run: python scripts/build_grid_site.py\n      - name: Credit feeds")
    assert grid_steps_left(planted) == ["scripts/build_grid_site.py"]


def test_grid_scripts_stay_in_the_repo():
    for rel in GRID_ONLY:
        assert (ROOT / rel).exists(), rel


def test_status_step_reports_credit_alone():
    body = run_lines(WF)
    assert "python scripts/run_status.py --credit-only" in body
    assert "--mstr-status" not in body and "--ticker-status" not in body


def frozen_line(rel: str):
    return re.search(r'<p class="frozen">This page is no longer updated\. Last update: '
                     r'<time datetime="(\d{4}-\d{2}-\d{2})">([^<]+)</time>\. <a href="\.\./">DATproof home</a></p>',
                     (ROOT / rel).read_text())


def test_grid_page_says_it_is_frozen_with_its_last_build_date():
    page = (ROOT / "site" / "grid" / "index.html").read_text()
    m = frozen_line("site/grid/index.html")
    assert m, "no frozen line on /grid/"
    assert page.index('class="frozen"') < page.index("<nav>")  # at the top
    generated = re.search(r'"generated":"(\d{4}-\d{2}-\d{2})"', page).group(1)
    assert m.group(1) == generated, "the line's date must be the page's own build date"
    d = dt.date.fromisoformat(generated)
    assert m.group(2) == f"{d.day} {d.strftime('%b %Y')}"
    t = frozen_line("site/grid/template.html")
    assert t and t.group(1) == generated


def test_story_page_still_points_at_grid():
    assert "url=../grid/#stress" in (ROOT / "site" / "story" / "index.html").read_text()


def test_llms_and_sitemap_never_send_readers_to_grid_or_story():
    for rel in ("site/llms.txt", "site/sitemap.xml"):
        text = (ROOT / rel).read_text()
        assert "/grid" not in text and "/story" not in text, rel


def test_feed_imports_no_grid_script_but_the_sec_contact():
    """The feed's only import from scripts/ is the SEC contact fallback in sources.sec_user_agent, used only
    when SEC_USER_AGENT is unset; parse_sata now comes from datproof_feed/strive_sata.py."""
    hits = []
    for p in sorted((ROOT / "datproof_feed").glob("*.py")):
        for ln in p.read_text().splitlines():
            if re.match(r"\s*(from scripts|import scripts)", ln):
                hits.append((p.name, ln.strip()))
    assert hits == [("sources.py", "from scripts.pull_mstr import USER_AGENT")]


@pytest.mark.parametrize("ahead", [10, 40])
def test_credit_only_status_never_ages(tmp_path, monkeypatch, ahead):
    """The old filing-date check would go red about three weeks after the pulls stopped; the credit-only
    report has no date check and never stops the job."""
    out = tmp_path / "run-status.json"
    monkeypatch.setattr(run_status, "OUT", out)
    later = dt.date.today() + dt.timedelta(days=ahead)
    status = run_status.build_status({"credit": "ok"}, today=later, filings_too=False)
    assert status["stale_days"] is None and status["latest_filing"] == {} and not status["degraded"]
    assert run_status.main(["--credit-only"]) == 0
    assert run_status.main(["--credit-only", "--credit-status", "failed"]) == 0
    written = json.loads(out.read_text())
    assert written["sources"] == {"credit": "failed"} and written["degraded"] is True


def test_old_status_check_would_have_aged():
    """Why the old check had to go: 40 days after the newest filing, the frozen data reads as stale."""
    newest = max(d for d in run_status.latest_filings().values() if d)
    later = dt.date.fromisoformat(newest) + dt.timedelta(days=40)
    assert run_status.build_status({"mstr": "ok"}, today=later)["stale_days"] > run_status.STALE_DAYS_LIMIT
