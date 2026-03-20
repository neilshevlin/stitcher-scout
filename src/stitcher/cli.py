"""CLI entry point for stitcher."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated, Optional

import typer
from rich.console import Console

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


async def _scout_async(
    description: str,
    repo: str | None,
    mode: str,
    model: str | None,
    output: str | None,
    output_json: bool,
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

    try:
        report = await run_scout(description, repo, settings)

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
) -> None:
    """Search GitHub for real, working code relevant to your project."""
    asyncio.run(_scout_async(description, repo, mode, model, output, output_json))


@app.command()
def version() -> None:
    """Show the version."""
    console.print(f"stitcher {__version__}")
