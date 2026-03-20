"""Orchestrator — wires the decompose-search-evaluate-refine loop together."""

from __future__ import annotations

from rich.console import Console

from .config import Settings
from .context import parse_project_context
from .decomposer import decompose
from .deps import create_dep_search_brief, extract_deps_from_results
from .evaluator import evaluate
from .github_client import GitHubClient
from .llm import LLMClient, LLMError
from .models import EvaluatedResult, ScoutReport, SubproblemReport
from .refiner import refine
from .searcher import execute_briefs

console = Console(stderr=True)


class ScoutError(Exception):
    """User-facing error from the scout pipeline."""


async def run_scout(
    description: str,
    repo_path: str | None,
    settings: Settings,
) -> ScoutReport:
    """Run the full scout pipeline and return a report."""
    gh = GitHubClient(settings.github_token)
    llm = LLMClient()
    model = settings.model

    try:
        # 1. Parse project context
        with console.status("[bold green]Parsing project context..."):
            context = await parse_project_context(description, repo_path, gh)

        # 2. Decompose into search briefs
        with console.status("[bold green]Decomposing into sub-problems..."):
            try:
                briefs = await decompose(context, llm, model=model)
            except LLMError as e:
                raise ScoutError(f"Failed to decompose project: {e}") from e
        console.print(f"  [dim]Identified {len(briefs)} sub-problems[/dim]")

        all_evaluated: dict[str, list[EvaluatedResult]] = {}
        all_briefs: dict[str, object] = {}
        all_observations: list[str] = []
        all_gaps: list[str] = []
        iteration = 0
        max_loops = 0 if settings.mode == "fast" else settings.max_refinement_loops
        total_iterations = max_loops + 1

        while True:
            # Track briefs
            for b in briefs:
                all_briefs[b.id] = b

            # 3. Execute searches + enrich with quality signals
            query_count = sum(len(b.queries) for b in briefs)
            label = f"[bold green]Searching GitHub ({query_count} queries, pass {iteration + 1}/{total_iterations})...[/bold green]"
            with console.status(label):
                results = await execute_briefs(briefs, gh)
            unique_repos = len({r.repo.full_name for r in results})
            console.print(f"  [dim]Found {len(results)} results from {unique_repos} repos[/dim]")

            # 4. Evaluate results per brief
            eval_count = 0
            for brief in briefs:
                brief_results = [r for r in results if r.brief_id == brief.id]
                if not brief_results:
                    continue

                label = f"[bold green]Evaluating: {brief.subproblem[:50]}... (pass {iteration + 1}/{total_iterations})[/bold green]"
                with console.status(label):
                    try:
                        evaluated = await evaluate(
                            brief_results,
                            context,
                            brief,
                            gh,
                            llm,
                            model=model,
                            max_candidates=settings.max_candidates_per_subproblem,
                            max_lines=settings.max_file_lines,
                        )
                    except LLMError as e:
                        console.print(f"  [yellow]Warning: evaluation failed for '{brief.subproblem[:40]}': {e}[/yellow]")
                        continue
                all_evaluated.setdefault(brief.id, []).extend(evaluated)
                eval_count += len(evaluated)
                console.print(f"  [dim]{brief.subproblem[:40]}: {len(evaluated)} good results[/dim]")

            console.print(f"  [dim]Pass {iteration + 1} complete: {eval_count} results evaluated[/dim]")

            # 4.5. Dependency following (after first evaluation pass)
            if iteration == 0 and all_evaluated:
                with console.status("[bold green]Analyzing dependencies of top results..."):
                    discovered_deps = await extract_deps_from_results(all_evaluated, gh)

                if discovered_deps:
                    console.print(f"  [dim]Discovered {len(discovered_deps)} dependencies: {', '.join(discovered_deps[:8])}...[/dim]")
                    dep_brief = create_dep_search_brief(discovered_deps, language=context.language)
                    if dep_brief:
                        with console.status("[bold green]Searching for discovered libraries..."):
                            dep_results = await execute_briefs([dep_brief], gh)

                        if dep_results:
                            with console.status("[bold green]Evaluating discovered libraries..."):
                                try:
                                    dep_evaluated = await evaluate(
                                        dep_results,
                                        context,
                                        dep_brief,
                                        gh,
                                        llm,
                                        model=model,
                                        max_candidates=settings.max_candidates_per_subproblem,
                                        max_lines=settings.max_file_lines,
                                    )
                                    if dep_evaluated:
                                        all_evaluated[dep_brief.id] = dep_evaluated
                                        all_briefs[dep_brief.id] = dep_brief
                                        console.print(f"  [dim]Dependency analysis: {len(dep_evaluated)} useful libraries found[/dim]")
                                except LLMError as e:
                                    console.print(f"  [yellow]Warning: dependency evaluation failed: {e}[/yellow]")

            iteration += 1
            if iteration > max_loops:
                break

            # 5. Refine
            with console.status(f"[bold green]Refining searches (pass {iteration}/{total_iterations})..."):
                try:
                    refinement = await refine(all_evaluated, briefs, context, llm, model=model)
                except LLMError as e:
                    console.print(f"  [yellow]Warning: refinement failed: {e}. Proceeding with current results.[/yellow]")
                    break

            all_observations.extend(refinement.observations)
            all_gaps.extend(refinement.gaps)

            if not refinement.should_continue or not refinement.new_briefs:
                console.print("  [dim]Coverage sufficient, no further refinement needed[/dim]")
                break

            console.print(f"  [dim]Refining: {len(refinement.new_briefs)} new searches using extracted vocabulary[/dim]")
            briefs = refinement.new_briefs

        # 6. Build report
        subproblem_reports = []
        for brief_id, evaluated_list in all_evaluated.items():
            brief = all_briefs.get(brief_id)
            subproblem_reports.append(
                SubproblemReport(
                    subproblem=brief.subproblem if brief else brief_id,
                    search_briefs_used=[brief_id],
                    recommended=sorted(
                        evaluated_list,
                        key=lambda e: (e.relevance_score + e.quality_score) / 2,
                        reverse=True,
                    )[:5],
                )
            )

        total_results = sum(len(sp.recommended) for sp in subproblem_reports)
        console.print(f"\n[bold green]Done![/bold green] Found {total_results} recommended repos across {len(subproblem_reports)} sub-problems.")

        return ScoutReport(
            project_understanding=f"Searching for implementations related to: {description}",
            subproblems=subproblem_reports,
            unexpected_findings=all_observations,
            gaps=all_gaps,
        )

    finally:
        await gh.close()
