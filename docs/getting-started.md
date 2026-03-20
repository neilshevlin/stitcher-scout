# Getting Started

This guide walks you through installing stitcher-scout, setting up credentials, and running your first search.

## Installation

### From PyPI

```bash
pip install stitcher-scout
```

Or with [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install stitcher-scout
```

### From source

```bash
git clone https://github.com/neilshevlin/stitcher.git
cd stitcher
uv tool install .
```

After installation, two commands are available:

- `stitcher` — the CLI tool
- `stitcher-mcp` — the MCP server for Claude Code integration

Verify the installation:

```bash
stitcher version
```

## Credentials

Stitcher needs two things: a GitHub token for searching repos, and an API key for the LLM that evaluates results.

### Quick setup

The easiest way to configure credentials is the interactive setup wizard:

```bash
stitcher setup
```

This will detect existing credentials (environment variables, `gh` CLI auth, system keychain) and prompt you for anything missing. It can optionally store keys in your system keychain for future use.

### Credential resolution

Stitcher checks for credentials in this order:

1. **Environment variables** — `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, etc.
2. **`.env` file** — in your working directory
3. **`gh` CLI** — if you have the [GitHub CLI](https://cli.github.com) installed and authenticated, stitcher uses your `gh auth token` automatically (zero setup for gh users)
4. **System keychain** — macOS Keychain, Linux secret-service, etc. (requires `pip install stitcher-scout[keychain]`)
5. **Interactive prompt** — `stitcher setup` asks for keys and offers to save them to your keychain

### GitHub token

If you don't have the `gh` CLI, create a token manually:

1. Go to [GitHub Settings > Fine-grained tokens](https://github.com/settings/personal-access-tokens/new)
2. Give it a name (e.g. "stitcher")
3. Set expiration to your preference
4. Under **Repository access**, select "Public Repositories (read-only)"
5. Under **Permissions**, grant:
   - **Contents**: Read-only
   - **Metadata**: Read-only
6. Click "Generate token" and copy it

```bash
export GITHUB_TOKEN="github_pat_..."
```

### LLM API key

Set the key for whichever provider you want to use:

```bash
# Anthropic (default model: claude-sonnet-4-20250514)
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# Google Gemini
export GEMINI_API_KEY="..."

# Local models via Ollama need no key
```

### Using a `.env` file

Instead of exporting variables, create a `.env` file in your working directory:

```
GITHUB_TOKEN=github_pat_...
ANTHROPIC_API_KEY=sk-ant-...
```

See `.env.example` in the repo for a full template.

## Your first search

Run a quick search:

```bash
stitcher scout "A CLI tool that converts markdown files to PDF with syntax highlighting"
```

This will:

1. Decompose the description into sub-problems (core libraries, PDF generation, syntax highlighting, etc.)
2. Search GitHub for relevant repos using multiple query strategies
3. Read actual source code from candidate repos
4. Score each result for relevance and quality
5. Print a markdown report with recommended repos and specific files to look at

### Save the report

```bash
stitcher scout -o report.md "Real-time collaborative text editor in TypeScript"
```

### Use a different model

```bash
stitcher scout --model gpt-4o "WebSocket server with authentication"
```

### Deep search

For more thorough results, use deep mode. This runs multiple refinement passes, extracting domain vocabulary from initial results to find repos that use different terminology:

```bash
stitcher scout --mode deep "GPU cluster scheduler with preemption support"
```

### Search with project context

Point stitcher at an existing repo so it understands your stack:

```bash
stitcher scout --repo /path/to/my-project "Add real-time notifications"
```

Or a GitHub URL:

```bash
stitcher scout --repo https://github.com/org/my-project "Add real-time notifications"
```

## Preview the search strategy

Use `--explain` to see what stitcher will search for before it runs:

```bash
stitcher scout --explain "Event sourcing in Go"
```

This shows a formatted table of sub-problems, query types, and total query count.

## Generate a research brief

Use `--brief` to produce a model-agnostic research brief and a starter dependency manifest alongside the report:

```bash
stitcher scout --brief "REST API with authentication in Python"
```

The brief includes per-subproblem recommendations, install commands, specific files to study, and a `requirements.txt` / `Cargo.toml` / `package.json` / `go.mod` snippet. Use `--brief-language` to override the target language.

## JSON output

For programmatic use, get structured JSON:

```bash
stitcher scout --json "Event sourcing in Go" > results.json
```

The JSON includes sub-problems, recommended repos with scores, relevant file paths with line ranges, and identified gaps.

## Cache management

Stitcher caches GitHub API responses locally to speed up repeated searches and reduce API usage. To clear the cache:

```bash
stitcher cache-clear
```

The cache is stored at `~/.cache/stitcher-scout/` (override with `STITCHER_CACHE_DIR`).

## Next steps

- [How It Works](./how-it-works.md) — understand the pipeline and scoring
- [Configuration](./configuration.md) — all settings and environment variables
- [MCP Integration](./mcp-integration.md) — use stitcher as a tool in Claude Code
