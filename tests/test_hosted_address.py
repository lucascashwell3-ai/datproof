"""The hosted copy of the plug-in is named the same way everywhere, and the Worker config matches it.

One address lives in datproof_feed/pages.py (HOSTED_MCP). README, the home page, its Markdown twin and llms.txt
name it; the privacy page and its twin name its host and no longer say there is no hosted version;
worker/wrangler.toml serves that host only, as a custom domain, with no workers.dev address and logs off.
Each check is planted to fail once."""
from __future__ import annotations

import functools
import pathlib
import re
import tomllib

from datproof_feed import pages

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
WRANGLER = ROOT / "worker" / "wrangler.toml"
OLD_CLAIM = "There is no hosted version"
ANY_HOSTED = re.compile(r"https://mcp\.[\w.-]+/[\w/-]*")
NAMES_IT = ("README.md", "index.html", "index.md", "llms.txt")


@functools.lru_cache(maxsize=1)
def rendered() -> dict[str, str]:
    feed = pages.load(SITE / "v1")
    out = pages.render(feed, (SITE / "index.html").read_text(), pages.load_config(SITE))
    return {**out, "README.md": (ROOT / "README.md").read_text()}


def address_problems(files: dict[str, str]) -> list[str]:
    out = []
    for rel in NAMES_IT:
        text = files.get(rel, "")
        if pages.HOSTED_MCP not in text:
            out.append(f"{rel} does not name {pages.HOSTED_MCP}")
        out += [f"{rel} names another hosted address: {a}" for a in set(ANY_HOSTED.findall(text)) - {pages.HOSTED_MCP}]
    return out


def privacy_problems(files: dict[str, str]) -> list[str]:
    out = []
    for rel in ("privacy/index.html", "privacy/index.md"):
        text = files.get(rel, "")
        if OLD_CLAIM in text:
            out.append(f"{rel} still says: {OLD_CLAIM}")
        if pages.HOSTED_HOST not in text:
            out.append(f"{rel} does not name {pages.HOSTED_HOST}")
        if "Cloudflare" not in text:
            out.append(f"{rel} does not name Cloudflare")
    return out


def wrangler_problems(text: str) -> list[str]:
    conf = tomllib.loads(text)
    out = []
    if conf.get("workers_dev") is not False:
        out.append("workers_dev is not false")
    if conf.get("preview_urls") is not False:
        out.append("preview_urls is not false")
    if conf.get("routes") != [{"pattern": pages.HOSTED_HOST, "custom_domain": True}]:
        out.append(f"routes is not the one custom domain {pages.HOSTED_HOST}: {conf.get('routes')}")
    if (conf.get("observability") or {}).get("enabled") is not False:
        out.append("observability (request logs) is not off")
    if conf.get("vars") or conf.get("analytics_engine_datasets"):
        out.append("variables or a call count are set")
    return out


# ---------- the real files ----------

def test_constants_agree():
    assert pages.HOSTED_MCP == "https://mcp.datproof.com/mcp"
    assert pages.HOSTED_HOST == "mcp.datproof.com"


def test_every_copy_names_the_one_hosted_address():
    assert address_problems(rendered()) == []


def test_written_pages_match_the_build():
    files = rendered()
    for rel in ("index.html", "index.md", "llms.txt", "privacy/index.html", "privacy/index.md"):
        assert (SITE / rel).read_text() == files[rel], f"site/{rel} is stale: run python -m datproof_feed.pages"


def test_privacy_page_names_the_hosted_copy():
    assert privacy_problems(rendered()) == []


def test_wrangler_matches_what_is_live():
    assert wrangler_problems(WRANGLER.read_text()) == []


# ---------- planted failures: each check catches its own break ----------

def test_planted_missing_address_is_caught():
    files = dict(rendered())
    files["llms.txt"] = files["llms.txt"].replace(pages.HOSTED_MCP, "")
    assert any(p.startswith("llms.txt does not name") for p in address_problems(files))


def test_planted_other_address_is_caught():
    files = dict(rendered())
    files["README.md"] += "\nAlso at https://mcp.example.org/mcp\n"
    assert any("another hosted address" in p for p in address_problems(files))


def test_planted_old_privacy_claim_is_caught():
    files = dict(rendered())
    files["privacy/index.md"] = files["privacy/index.md"].replace(pages.HOSTED_HOST, "x") + OLD_CLAIM
    found = privacy_problems(files)
    assert any("still says" in p for p in found) and any("does not name mcp" in p for p in found)


def test_planted_wrangler_breaks_are_caught():
    good = WRANGLER.read_text()
    assert any("workers_dev" in p for p in wrangler_problems(good.replace("workers_dev = false", "workers_dev = true")))
    assert any("routes" in p for p in wrangler_problems(good.replace("custom_domain = true", "custom_domain = false")))
    assert any("observability" in p for p in wrangler_problems(good.replace("enabled = false", "enabled = true")))
    assert any("variables" in p for p in wrangler_problems(good + '\n[vars]\nDATPROOF_COUNT = "1"\n'))
