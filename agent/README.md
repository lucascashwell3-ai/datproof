# datproof-agent

An MCP server that lets any AI assistant — Claude Desktop, claude.ai, ChatGPT, Cursor, or
anything else that speaks the Model Context Protocol — answer questions about a Bitcoin
treasury company's SEC filings with the filing attached. Every number it returns carries the
filing's accession number and source URL, so an answer can be checked against the original
document rather than taken on faith. It covers Strive, Inc. (ASST common / SATA preferred)
today; the design is company-agnostic — every tool takes a `company` argument, resolved
against a small registry, so covering another company is one registry entry, not a rewrite.

## Install

```bash
pip install -e agent
```

or, without installing anything permanently:

```bash
uvx --from ./agent datproof-agent
```

Either way you get a `datproof-agent` command that speaks MCP over stdio by default. Add
`--http` to serve streamable HTTP on a port instead (`--host` / `--port` to change where):

```bash
datproof-agent --http --port 8000
```

## Data source

Reads the ledger this repo publishes at
`https://lucascashwell3-ai.github.io/datproof/api/<company>/{history,latest,diff,dividends}.json`
— built from the company's own SEC filings by `scripts/ledger_asst.py`, nothing here is
estimated. If the site request fails (it 404s until the site is deployed), it falls back to a
local checkout's `data/ledger/<company>/` directory; point it at one with the
`DATPROOF_LEDGER_DIR` environment variable. Whichever it used is in every response's
`data_source` field. Data is cached in memory for the life of the process — restart the server
to pick up a new filing.

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "datproof": {
      "command": "datproof-agent"
    }
  }
}
```

(If you used `uvx` instead of installing, use `"command": "uvx", "args": ["--from", "/path/to/datproof/agent", "datproof-agent"]`.)

## claude.ai (custom connector)

Custom connectors on claude.ai talk to a remote server, so run the server with `--http` on a
host claude.ai can reach (a small VM, a tunnel, etc.), then in **Settings → Connectors → Add
custom connector**, enter:

```
http://<your-host>:8000/mcp
```

## Cursor

Add to `~/.cursor/mcp.json` (or your project's `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "datproof": {
      "command": "datproof-agent"
    }
  }
}
```

## Tools

| Tool | Example question |
|---|---|
| `list_companies()` | Which companies does this cover? |
| `latest(company)` | What did Strive's latest 8-K disclose? |
| `filings(company, limit=20)` | Show me Strive's last 5 weekly filings. |
| `metric(company, name, as_of=None)` | What was Strive's dividend coverage on August 31? |
| `compare(company, accession_a, accession_b)` | How did Strive's Aug 24 filing compare to Aug 17? |
| `diff(company)` | Did this week's filing reconcile with last week's? |
| `stress(company, btc_price, accession=None)` | What is Strive's dividend coverage if Bitcoin falls to $40,000? |
| `dividends(company)` | What is Strive's SATA dividend rate and annual payout? |
| `definitions()` | What does CEBE mean? |
| `source(company, accession, field)` | Which filing states Strive's cash on Sept 11, and what exactly does it say? |

`demo_questions.json` in this directory has 12 harder examples — real tool calls against the
live ledger, with the real JSON they returned — including one the ledger honestly can't
answer (warrant strike price isn't in the filings' holdings table).

## Never estimated

A value the filing didn't state comes back `null` with a note, never filled in or guessed. An
unknown company or metric name returns a plain-sentence error listing the valid ones.
