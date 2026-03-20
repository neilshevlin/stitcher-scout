# stitcher-scout

LLM-powered GitHub code scout — finds real, working code relevant to your project.

Give it a description of what you want to build. It decomposes the problem into sub-problems, searches GitHub for implementations, reads actual source code to evaluate quality and relevance, and produces a structured report with recommended repositories and files.

Works with any LLM provider: OpenAI, Anthropic, Google Gemini, Ollama, and [100+ others via litellm](https://docs.litellm.ai/docs/providers).

## Quick start

```bash
pip install stitcher-scout
```

```bash
stitcher setup    # interactive credential setup (or set env vars manually)
```

```bash
stitcher scout "A real-time multiplayer game server in Rust with WebSocket support"
```

See [Getting Started](getting-started.md) for full setup instructions.

## What it does

```
Description ──► Decompose ──► Search ──► Evaluate ──► Report
                                  ▲          │
                                  │          ▼
                                  └── Refine ◄── (deep mode only)
```

1. **Decompose** — An LLM breaks your description into sub-problems (core libraries, architecture patterns, specific features)
2. **Search** — Each sub-problem generates multiple GitHub queries with stratified search (by stars, recency, mid-range). Results are cached locally for speed.
3. **Evaluate** — The LLM reads actual source code from candidate repos, scoring relevance and quality
4. **Deduplicate** — Repos appearing across multiple sub-problems are consolidated; cross-cutting "Swiss Army knife" repos are flagged
5. **Refine** (deep mode) — Extracts domain vocabulary from top results, follows dependency graphs, generates new searches
6. **Report** — Produces a structured report with recommended repos, ecosystem map, patterns & insights, quality signals, and cost summary

See [How It Works](how-it-works.md) for the full pipeline breakdown.

## Use as a CLI tool

```bash
# Quick search
stitcher scout "OAuth2 service with PKCE flow"

# Deep search with refinement
stitcher scout --mode deep "GPU cluster scheduler"

# Preview the search strategy before running
stitcher scout --explain "GPU cluster scheduler"

# Generate a research brief + dependency manifest
stitcher scout --brief "WebSocket server in Python"

# Use a different model
stitcher scout --model gpt-4o "Event sourcing in Go"

# Save report to file
stitcher scout -o report.md "WebSocket server in Python"
```

## Use as an MCP tool in Claude Code

```bash
claude mcp add --scope user stitcher stitcher-mcp
```

After restarting Claude Code, the `scout` tool is available for AI-assisted project research. See [MCP Integration](mcp-integration.md).

## Supported models

| Provider | Example | Env var |
|----------|---------|---------|
| Anthropic | `claude-sonnet-4-20250514` (default) | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Google Gemini | `gemini/gemini-2.0-flash` | `GEMINI_API_KEY` |
| Ollama (local) | `ollama/llama3` | None |
| OpenRouter | `openrouter/anthropic/claude-3.5-sonnet` | `OPENROUTER_API_KEY` |
| Together AI | `together_ai/meta-llama/Llama-3-70b` | `TOGETHER_API_KEY` |

See [Configuration](configuration.md) for all settings.

## License

MIT
