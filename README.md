# stitcher-scout

LLM-powered GitHub code scout — finds real, working code relevant to your project.

Give it a description of what you want to build. It decomposes the problem into sub-problems, searches GitHub for implementations, reads actual source code to evaluate quality and relevance, and produces a structured report with recommended repositories and files.

Works with any LLM provider: OpenAI, Anthropic, Google Gemini, Ollama, and [100+ others via litellm](https://docs.litellm.ai/docs/providers).

## Install

```bash
pip install stitcher-scout
# or
uv tool install stitcher-scout
```

## Setup

You need a GitHub token and an API key for your LLM provider:

```bash
export GITHUB_TOKEN="ghp_..."  # GitHub personal access token (read-only)

# Set whichever provider you use:
export ANTHROPIC_API_KEY="sk-ant-..."
# or
export OPENAI_API_KEY="sk-..."
# or
export GEMINI_API_KEY="..."
```

Or create a `.env` file in your working directory (see `.env.example`).

## CLI Usage

```bash
# Quick search (uses default model)
stitcher scout "A real-time multiplayer game server in Rust with WebSocket support"

# Use a specific model
stitcher scout --model gpt-4o "OAuth2 authentication service with PKCE flow"

# Deep search with iterative refinement
stitcher scout --mode deep "Cloud-based wind farm SCADA system with real-time turbine monitoring"

# Save report to file
stitcher scout -o report.md "Event sourcing framework in Go"

# Get structured JSON output (useful for piping)
stitcher scout --json "WebSocket server in Python"

# Use an existing repo for context
stitcher scout --repo /path/to/myproject "Add WebSocket support"
```

### Supported models

Any model string that [litellm supports](https://docs.litellm.ai/docs/providers):

| Provider | Example `--model` value | Env var needed |
|---|---|---|
| Anthropic | `claude-sonnet-4-20250514` (default) | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Google Gemini | `gemini/gemini-2.0-flash` | `GEMINI_API_KEY` |
| Ollama (local) | `ollama/llama3` | None (runs locally) |
| OpenRouter | `openrouter/anthropic/claude-3.5-sonnet` | `OPENROUTER_API_KEY` |
| Together AI | `together_ai/meta-llama/Llama-3-70b` | `TOGETHER_API_KEY` |

## MCP Server (Claude Code integration)

stitcher-scout ships as an MCP server so Claude Code can use it as a tool during project planning.

### Add to Claude Code

Globally (available in all projects):

```bash
claude mcp add --scope user stitcher stitcher-mcp
```

Or per-project, add to `.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "stitcher": {
      "command": "stitcher-mcp"
    }
  }
}
```

Restart Claude Code after configuring. The `scout` tool will be available for searching GitHub and returning structured results. See [MCP Integration](docs/mcp-integration.md) for details.

## How it works

1. **Decompose** — An LLM breaks your description into sub-problems (core libraries, architecture patterns, specific features)
2. **Search** — Each sub-problem generates multiple GitHub queries with stratified search (by stars, recency, mid-range)
3. **Evaluate** — The LLM reads actual source code from candidate repos, scoring relevance and quality
4. **Refine** (deep mode) — Extracts domain vocabulary from top results, follows dependency graphs, generates new searches
5. **Report** — Produces a structured report with recommended repos, relevant files, quality signals, and caveats

### Quality signals

Repos are scored on: stars, forks, contributors, recency, CI presence, license, releases, org ownership, and age. A focus score penalises incidental matches in large repos.

## Configuration

All settings can be set via environment variables or `.env` file:

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | *required* | GitHub personal access token |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / etc. | *required* | API key for your LLM provider |
| `STITCHER_MODEL` | `claude-sonnet-4-20250514` | LLM model string |
| `STITCHER_MODE` | `fast` | `fast` or `deep` |
| `STITCHER_MAX_REFINEMENT_LOOPS` | `3` | Max refinement iterations (deep mode) |
| `STITCHER_MAX_CANDIDATES_PER_SUBPROBLEM` | `5` | Max repos to evaluate per sub-problem |
| `STITCHER_MAX_FILE_LINES` | `500` | Max lines of code to read per file |

## Documentation

- [Getting Started](docs/getting-started.md) — installation, credentials, first search
- [How It Works](docs/how-it-works.md) — pipeline stages, scoring, search strategies
- [Configuration](docs/configuration.md) — all settings and environment variables
- [MCP Integration](docs/mcp-integration.md) — using stitcher as a tool in Claude Code

## License

MIT
