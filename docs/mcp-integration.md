# MCP Integration

Stitcher ships as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, so AI coding assistants like Claude Code can use it as a tool during project planning.

## Setup

### Global (all projects)

Add stitcher to your global Claude Code config. If you've installed via `pip` or `uv tool install`:

```bash
claude mcp add --scope user stitcher stitcher-mcp
```

Or using `uvx` (no install needed — fetches from PyPI on first run):

```bash
claude mcp add --scope user stitcher uvx stitcher-scout stitcher-mcp
```

### Per-project

Add to `.mcp.json` at your project root:

```json
{
  "mcpServers": {
    "stitcher": {
      "command": "stitcher-mcp"
    }
  }
}
```

### With API keys

If your keys aren't in the shell environment, pass them via the MCP config:

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

After configuring, restart Claude Code. The `scout` tool will appear in the available tools list.

## Tool interface

The MCP server exposes a single tool:

### `scout`

Search GitHub for real, working code relevant to a project description.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `description` | string | Yes | What you want to build — describe the project or feature. |
| `repo` | string | No | Path or GitHub URL to an existing repo for context. |
| `mode` | string | No | `"fast"` (default) or `"deep"` (iterative refinement). |
| `model` | string | No | LLM model override (e.g., `"gpt-4o"`). Uses config default if not set. |
| `save_report` | string | No | Directory path to write a `.md` report file. |
| `generate_brief` | boolean | No | When `true`, include a research brief and starter dependency manifest in the response. |
| `brief_language` | string | No | Target language for the dependency manifest (e.g., `"python"`, `"rust"`). Auto-detected if not set. |

**Returns:** JSON string with:

```json
{
  "project_understanding": "Summary of what you're building",
  "subproblems": [
    {
      "subproblem": "Core libraries and frameworks",
      "recommended": [
        {
          "repo": "owner/repo-name",
          "url": "https://github.com/owner/repo-name",
          "description": "...",
          "stars": 2500,
          "forks": 180,
          "language": "Rust",
          "relevance_score": 0.85,
          "quality_score": 0.78,
          "repo_quality_score": 0.82,
          "summary": "What this repo does and why it's relevant",
          "caveats": "Things to be aware of",
          "relevant_files": [
            {
              "path": "src/core/parser.rs",
              "start_line": 42,
              "end_line": 120,
              "explanation": "Core parsing logic"
            }
          ]
        }
      ]
    }
  ],
  "unexpected_findings": ["Interesting discoveries"],
  "gaps": ["Sub-problems with no good results"]
}
```

If `save_report` is provided, the response also includes `"report_file": "/path/to/report.md"`.

When `generate_brief` is `true`, the response also includes:

```json
{
  "research_brief": "# Research Brief\n...",
  "deps_manifest": "# requirements.txt — generated from scout results\n..."
}
```

## Usage examples

Once configured, Claude Code can use stitcher during conversations:

**Direct request:**
> "Use the scout tool to find implementations of real-time collaborative editing in TypeScript"

**During project planning:**
> "I want to build a GPU cluster scheduler. Research what's out there on GitHub before we start."

**With report output:**
> "Search for OAuth2 PKCE implementations and save the report to ./research/"

**With project context:**
> "Scout for notification system implementations, using our repo for context"

**With research brief:**
> "Search for authentication libraries and generate a research brief with dependency recommendations"

## How it works with agents

When an AI agent calls the `scout` tool, the full pipeline runs: decomposition, search, code evaluation, and (in deep mode) refinement. The structured JSON response gives the agent detailed information about each recommended repo, including specific files and line ranges to examine.

This is useful for:

- **Project planning** — understanding what already exists before building
- **Architecture decisions** — finding proven patterns and implementations
- **Library discovery** — finding the right dependencies for a new project
- **Due diligence** — evaluating the ecosystem around a technology
