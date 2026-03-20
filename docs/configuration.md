# Configuration

All settings are loaded from environment variables or a `.env` file in your working directory. No configuration files are required beyond the API keys.

## Environment variables

### Required

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | GitHub personal access token. Needs read-only access to public repos. [Create one here](https://github.com/settings/personal-access-tokens/new). |
| LLM API key | One of the provider keys listed below, matching your chosen model. |

### LLM provider keys

Set the key for whichever provider you use. Only one is needed.

| Variable | Provider | Example models |
|----------|----------|----------------|
| `ANTHROPIC_API_KEY` | Anthropic | `claude-sonnet-4-20250514` (default), `claude-opus-4-1` |
| `OPENAI_API_KEY` | OpenAI | `gpt-4o`, `gpt-4-turbo`, `o1`, `o3` |
| `GEMINI_API_KEY` | Google Gemini | `gemini/gemini-2.0-flash`, `gemini/gemini-pro` |
| `TOGETHER_API_KEY` | Together AI | `together_ai/meta-llama/Llama-3-70b` |
| `OPENROUTER_API_KEY` | OpenRouter | `openrouter/anthropic/claude-3.5-sonnet` |
| *(none)* | Ollama (local) | `ollama/llama3`, `ollama/mistral` |

Stitcher validates at startup that the correct key is set for the chosen model. You'll get a clear error like:

```
Model 'gpt-4o' requires OPENAI_API_KEY to be set. Set it in your environment or .env file.
```

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `STITCHER_MODEL` | `claude-sonnet-4-20250514` | LLM model string. Any [litellm-compatible model](https://docs.litellm.ai/docs/providers). |
| `STITCHER_MODE` | `fast` | Search mode. `fast` runs one pass. `deep` runs iterative refinement with vocabulary extraction. |
| `STITCHER_MAX_REFINEMENT_LOOPS` | `3` | Maximum refinement iterations in deep mode. |
| `STITCHER_MAX_CANDIDATES_PER_SUBPROBLEM` | `5` | Maximum repos to send to the LLM evaluator per sub-problem. Higher values find more results but cost more. |
| `STITCHER_MAX_FILE_LINES` | `500` | Maximum lines of source code to read per file during evaluation. |
| `STITCHER_DEBUG` | *(unset)* | Set to `1` to print full tracebacks on errors. |

## `.env` file

Create a `.env` file in your working directory:

```
GITHUB_TOKEN=github_pat_...
ANTHROPIC_API_KEY=sk-ant-...
```

The `.env` file is loaded automatically. Environment variables take precedence over `.env` values.

## CLI overrides

Some settings can be overridden per-run via CLI flags:

```bash
# Override model
stitcher scout --model gpt-4o "..."

# Override mode
stitcher scout --mode deep "..."
```

## MCP server environment

When running as an MCP server, environment variables must be available to the server process. In your MCP config, use the `env` field:

```json
{
  "mcpServers": {
    "stitcher": {
      "command": "stitcher-mcp",
      "env": {
        "GITHUB_TOKEN": "github_pat_...",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Or if the keys are already in your shell environment, the server will inherit them.

## Choosing a model

Stitcher uses the LLM for three tasks: decomposition, evaluation, and refinement. The quality of results depends on the model's ability to understand code and generate diverse search strategies.

Recommended models (best results → most affordable):

1. **`claude-sonnet-4-20250514`** (default) — Best balance of quality and cost
2. **`gpt-4o`** — Strong alternative, slightly different search strategies
3. **`gemini/gemini-2.0-flash`** — Fast and cheap, good for quick searches
4. **`ollama/llama3`** — Free, runs locally, but lower quality decomposition

The model is used for all three pipeline stages. There's no way to use different models for different stages (yet).
