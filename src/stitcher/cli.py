"""CLI entry point for stitcher."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__

app = typer.Typer(
    name="stitcher",
    help="GitHub Code Scout — find real, working code for your project.",
    no_args_is_help=True,
)
console = Console(stderr=True)
output_console = Console()


def _friendly_config_error(e: Exception) -> str:
    """Turn config validation errors into helpful messages."""
    msg = str(e)
    if "github_token" in msg.lower():
        return "GITHUB_TOKEN is not set. Get one at https://github.com/settings/tokens (read-only access is sufficient)."
    if "mode" in msg.lower():
        return str(e)
    return f"Configuration error: {e}\nSet GITHUB_TOKEN in your environment or .env file."


def _print_search_strategy(briefs: list) -> None:
    """Print a formatted summary of the search strategy to stderr."""
    total_queries = sum(len(b.queries) for b in briefs)

    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Sub-problem", style="bold", ratio=2)
    table.add_column("Level", style="dim", width=12)
    table.add_column("Queries", ratio=3)

    for brief in briefs:
        grouped: dict[str, list[str]] = {}
        for q in brief.queries:
            grouped.setdefault(q.search_type, []).append(q.query)

        query_lines = []
        for search_type in ("code", "repository", "topic"):
            queries = grouped.get(search_type, [])
            if queries:
                query_lines.append(f"[bold]{search_type}[/bold] ({len(queries)}):")
                for q in queries:
                    query_lines.append(f"  {q}")

        table.add_row(
            brief.subproblem,
            brief.level,
            "\n".join(query_lines),
        )

    panel = Panel(
        table,
        title=f"[bold]Search Strategy[/bold] — {len(briefs)} sub-problems, {total_queries} queries",
        border_style="blue",
    )
    console.print(panel)


async def _scout_async(
    description: str,
    repo: str | None,
    mode: str,
    model: str | None,
    output: str | None,
    output_json: bool,
    brief: bool = False,
    brief_language: str | None = None,
    explain: bool = False,
) -> None:
    from .agent import ScoutError, run_scout
    from .config import Settings

    try:
        kwargs: dict = {"mode": mode}
        if model:
            kwargs["model"] = model
        settings = Settings(**kwargs)  # type: ignore[arg-type]
    except Exception as e:
        console.print(f"[red]{_friendly_config_error(e)}[/red]")
        raise typer.Exit(1)

    on_decomposed = _print_search_strategy if explain else None

    try:
        report = await run_scout(description, repo, settings, on_decomposed=on_decomposed)

        if output_json:
            from .mcp_server import _report_to_dict
            result = _report_to_dict(report)
            raw = json.dumps(result, indent=2)
            if output:
                with open(output, "w") as f:
                    f.write(raw)
                console.print(f"[green]JSON report written to {output}[/green]")
            else:
                print(raw)
        else:
            from .presenter import render_markdown
            md = render_markdown(report)
            if output:
                with open(output, "w") as f:
                    f.write(md)
                console.print(f"[green]Report written to {output}[/green]")
            else:
                output_console.print(md)

        # Generate research brief and deps manifest when --brief is used
        if brief:
            from .brief import generate_brief, generate_deps_manifest, _detect_language

            lang = brief_language or _detect_language(report) or "python"
            brief_md = generate_brief(report, language=lang)
            deps_manifest = generate_deps_manifest(report, language=lang)

            if output:
                brief_path = f"{output}.md"
                deps_path = f"{output}.deps"
                with open(brief_path, "w") as f:
                    f.write(brief_md)
                with open(deps_path, "w") as f:
                    f.write(deps_manifest)
                console.print(f"[green]Research brief written to {brief_path}[/green]")
                console.print(f"[green]Dependency manifest written to {deps_path}[/green]")
            else:
                output_console.print("\n")
                output_console.print(brief_md)
                output_console.print("\n--- Dependency Manifest ---\n")
                output_console.print(deps_manifest)

    except ScoutError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        console.print("[dim]Run with STITCHER_DEBUG=1 for full traceback[/dim]")
        import os
        if os.environ.get("STITCHER_DEBUG"):
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def scout(
    description: Annotated[str, typer.Argument(help="Describe what you want to build")],
    repo: Annotated[Optional[str], typer.Option("--repo", "-r", help="Path or GitHub URL to your existing repo")] = None,
    mode: Annotated[str, typer.Option("--mode", "-m", help="Search mode: 'fast' (default) or 'deep' (iterative refinement)")] = "fast",
    model: Annotated[Optional[str], typer.Option("--model", help="LLM model (e.g. 'gpt-4o', 'claude-sonnet-4-20250514', 'gemini/gemini-2.0-flash')")] = None,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Write report to file instead of stdout")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Output structured JSON instead of markdown")] = False,
    brief: Annotated[bool, typer.Option("--brief", help="Generate a research brief and starter dependency manifest")] = False,
    brief_language: Annotated[Optional[str], typer.Option("--brief-language", help="Target language for the dependency manifest (e.g. 'python', 'rust', 'javascript', 'go')")] = None,
    explain: Annotated[bool, typer.Option("--explain", help="Show search strategy before executing")] = False,
) -> None:
    """Search GitHub for real, working code relevant to your project."""
    asyncio.run(_scout_async(description, repo, mode, model, output, output_json, brief, brief_language, explain=explain))


@app.command("cache-clear")
def cache_clear() -> None:
    """Clear the disk cache of GitHub API responses."""
    from .cache import clear_cache

    freed = clear_cache()
    if freed > 1_048_576:
        size_str = f"{freed / 1_048_576:.1f} MB"
    elif freed > 1024:
        size_str = f"{freed / 1024:.1f} KB"
    else:
        size_str = f"{freed} bytes"
    console.print(f"[green]Cache cleared.[/green] Freed {size_str}.")


@app.command()
def setup() -> None:
    """Set up credentials for stitcher (GitHub token + LLM API key)."""
    from .auth import resolve_github_token, resolve_llm_key, _get_gh_token

    console.print("[bold]stitcher setup[/bold]\n")

    # --- GitHub ---
    console.print("[bold]1. GitHub authentication[/bold]")
    import os

    if os.environ.get("GITHUB_TOKEN"):
        console.print("  [green]\u2713[/green] GITHUB_TOKEN found in environment")
    elif _get_gh_token():
        console.print("  [green]\u2713[/green] Found GitHub auth from gh CLI")
        console.print("  [dim]  stitcher will use your gh token automatically[/dim]")
    else:
        token = resolve_github_token(interactive=True)
        if token:
            console.print("  [green]\u2713[/green] GitHub token configured")
        else:
            console.print("  [red]\u2717[/red] No GitHub token configured")
            console.print("  [dim]  Set GITHUB_TOKEN or run: gh auth login[/dim]")

    # --- LLM ---
    console.print("\n[bold]2. LLM provider[/bold]")

    # Check which keys are already available
    providers = {
        "Anthropic": "ANTHROPIC_API_KEY",
        "OpenAI": "OPENAI_API_KEY",
        "Google Gemini": "GEMINI_API_KEY",
        "Together AI": "TOGETHER_API_KEY",
        "OpenRouter": "OPENROUTER_API_KEY",
    }
    found = []
    for name, env_var in providers.items():
        if os.environ.get(env_var):
            found.append(name)
            console.print(f"  [green]\u2713[/green] {env_var} found in environment")

    # Also check keychain
    from .auth import _keychain_get
    for name, env_var in providers.items():
        if name not in found and _keychain_get(env_var.lower()):
            found.append(name)
            console.print(f"  [green]\u2713[/green] {env_var} found in system keychain")

    if not found:
        from rich.prompt import Prompt
        console.print("  No LLM API key found.\n")
        choice = Prompt.ask(
            "  Provider",
            choices=["anthropic", "openai", "gemini", "together", "openrouter", "ollama"],
            default="anthropic",
            console=console,
        )
        if choice == "ollama":
            console.print("  [green]\u2713[/green] Ollama selected — no API key needed")
            console.print("  [dim]  Make sure Ollama is running: ollama serve[/dim]")
        else:
            env_var = providers.get(choice.title(), f"{choice.upper()}_API_KEY")
            # Map friendly names to env vars
            choice_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "together": "TOGETHER_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
            }
            env_var = choice_map.get(choice, f"{choice.upper()}_API_KEY")
            model_map = {
                "anthropic": "claude-sonnet-4-20250514",
                "openai": "gpt-4o",
                "gemini": "gemini/gemini-2.0-flash",
                "together": "together_ai/meta-llama/Llama-3-70b",
                "openrouter": "openrouter/anthropic/claude-3.5-sonnet",
            }
            key = resolve_llm_key(model_map.get(choice, "claude-sonnet-4-20250514"), interactive=True)
            if key:
                console.print(f"  [green]\u2713[/green] {env_var} configured")
            else:
                console.print(f"  [red]\u2717[/red] No API key configured")

    console.print("\n[green]Setup complete![/green]")
    console.print("Try: [bold]stitcher scout \"your project idea\"[/bold]")


@app.command()
def version() -> None:
    """Show the version."""
    console.print(f"stitcher {__version__}")
