"""Orchestrator — wires the decompose-search-evaluate-refine loop together."""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .config import Settings
from .context import parse_project_context
from .decomposer import decompose
from .deps import create_dep_search_brief, extract_deps_from_results
from .evaluator import evaluate
from .github_client import GitHubClient
from .llm import LLMClient, LLMError
from .models import EvaluatedResult, ScoutReport, SearchBrief, SubproblemReport, TokenUsageSummary
from .refiner import refine
from .searcher import execute_briefs

console = Console(stderr=True)


class ScoutError(Exception):
    """User-facing error from the scout pipeline."""


def _make_spinner() -> Progress:
    """Create a Progress bar with a spinner for indeterminate phases."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def _make_bar() -> Progress:
    """Create a Progress bar with a bar column for determinate phases."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


async def run_scout(
    description: str,
    repo_path: str | None,
    settings: Settings,
    progress: bool = True,
    on_decomposed: Callable[[list[SearchBrief]], None] | None = None,
) -> ScoutReport:
    """Run the full scout pipeline and return a report."""
    gh = GitHubClient(settings.github_token)
    llm = LLMClient()
    model = settings.model

    def _print(msg: str) -> None:
        if progress:
            console.print(msg)

    try:
        # 1. Parse project context
        if progress:
            with _make_spinner() as p:
                p.add_task("Parsing project context...")
                context = await parse_project_context(description, repo_path, gh)
        else:
            context = await parse_project_context(description, repo_path, gh)

        # 2. Decompose into search briefs
        if progress:
            with _make_spinner() as p:
                p.add_task("Decomposing problem...")
                try:
                    briefs = await decompose(context, llm, model=model)
                except LLMError as e:
                    raise ScoutError(f"Failed to decompose project: {e}") from e
        else:
            try:
                briefs = await decompose(context, llm, model=model)
            except LLMError as e:
                raise ScoutError(f"Failed to decompose project: {e}") from e
        _print(f"  [dim]Identified {len(briefs)} sub-problems[/dim]")

        if on_decomposed is not None:
            on_decomposed(briefs)

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
            search_desc = f"Searching GitHub... ({query_count} queries, pass {iteration + 1}/{total_iterations})"
            if progress:
                with _make_bar() as p:
                    task = p.add_task(search_desc, total=query_count)
                    results = await execute_briefs(briefs, gh)
                    p.update(task, completed=query_count)
            else:
                results = await execute_briefs(briefs, gh)

            unique_repos = len({r.repo.full_name for r in results})
            _print(f"  [dim]Found {len(results)} results from {unique_repos} repos[/dim]")

            # 4. Evaluate results per brief
            eval_count = 0
            briefs_with_results = [
                (brief, [r for r in results if r.brief_id == brief.id])
                for brief in briefs
            ]
            briefs_with_results = [(b, rs) for b, rs in briefs_with_results if rs]
            total_repos = sum(len(rs) for _, rs in briefs_with_results)

            if progress and briefs_with_results:
                with _make_bar() as p:
                    task = p.add_task(
                        f"Evaluating candidates... ({total_repos} repos)",
                        total=len(briefs_with_results),
                    )
                    for brief, brief_results in briefs_with_results:
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
                            _print(f"  [yellow]Warning: evaluation failed for '{brief.subproblem[:40]}': {e}[/yellow]")
                            p.advance(task)
                            continue
                        all_evaluated.setdefault(brief.id, []).extend(evaluated)
                        eval_count += len(evaluated)
                        p.advance(task)
            else:
                for brief, brief_results in briefs_with_results:
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
                    except LLMError:
                        continue
                    all_evaluated.setdefault(brief.id, []).extend(evaluated)
                    eval_count += len(evaluated)

            _print(f"  [dim]Pass {iteration + 1} complete: {eval_count} results evaluated[/dim]")

            # 4.5. Dependency following (after first evaluation pass)
            if iteration == 0 and all_evaluated:
                if progress:
                    with _make_spinner() as p:
                        p.add_task("Analyzing dependencies of top results...")
                        discovered_deps = await extract_deps_from_results(all_evaluated, gh)
                else:
                    discovered_deps = await extract_deps_from_results(all_evaluated, gh)

                if discovered_deps:
                    _print(f"  [dim]Discovered {len(discovered_deps)} dependencies: {', '.join(discovered_deps[:8])}...[/dim]")
                    dep_brief = create_dep_search_brief(discovered_deps, language=context.language)
                    if dep_brief:
                        if progress:
                            with _make_spinner() as p:
                                p.add_task("Searching for discovered libraries...")
                                dep_results = await execute_briefs([dep_brief], gh)
                        else:
                            dep_results = await execute_briefs([dep_brief], gh)

                        if dep_results:
                            if progress:
                                with _make_spinner() as p:
                                    p.add_task("Evaluating discovered libraries...")
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
                                            _print(f"  [dim]Dependency analysis: {len(dep_evaluated)} useful libraries found[/dim]")
                                    except LLMError as e:
                                        _print(f"  [yellow]Warning: dependency evaluation failed: {e}[/yellow]")
                            else:
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
                                except LLMError:
                                    pass

            iteration += 1
            if iteration > max_loops:
                break

            # 5. Refine
            if progress:
                with _make_spinner() as p:
                    p.add_task(f"Refining search... (pass {iteration}/{total_iterations})")
                    try:
                        refinement = await refine(all_evaluated, briefs, context, llm, model=model)
                    except LLMError as e:
                        _print(f"  [yellow]Warning: refinement failed: {e}. Proceeding with current results.[/yellow]")
                        break
            else:
                try:
                    refinement = await refine(all_evaluated, briefs, context, llm, model=model)
                except LLMError:
                    break

            all_observations.extend(refinement.observations)
            all_gaps.extend(refinement.gaps)

            if not refinement.should_continue or not refinement.new_briefs:
                _print("  [dim]Coverage sufficient, no further refinement needed[/dim]")
                break

            _print(f"  [dim]Refining: {len(refinement.new_briefs)} new searches using extracted vocabulary[/dim]")
            briefs = refinement.new_briefs

        # 6. Cross-subproblem deduplication
        repo_to_briefs: dict[str, list[str]] = {}
        repo_best_score: dict[str, tuple[float, str]] = {}

        for brief_id, evaluated_list in all_evaluated.items():
            brief = all_briefs.get(brief_id)
            subproblem_label = brief.subproblem if brief else brief_id
            for ev in evaluated_list:
                name = ev.search_result.repo.full_name
                repo_to_briefs.setdefault(name, [])
                if subproblem_label not in repo_to_briefs[name]:
                    repo_to_briefs[name].append(subproblem_label)
                avg = (ev.relevance_score + ev.quality_score) / 2
                prev_best, _ = repo_best_score.get(name, (-1.0, ""))
                if avg > prev_best:
                    repo_best_score[name] = (avg, brief_id)

        cross_cutting = {name: subs for name, subs in repo_to_briefs.items() if len(subs) > 1}
        for name, subs in cross_cutting.items():
            all_observations.append(
                f"Swiss Army knife repo: **{name}** is relevant to {len(subs)} sub-problems: "
                + ", ".join(subs)
            )

        for brief_id, evaluated_list in all_evaluated.items():
            deduped = []
            for ev in evaluated_list:
                name = ev.search_result.repo.full_name
                if name in cross_cutting:
                    _, best_brief = repo_best_score[name]
                    if best_brief != brief_id:
                        continue
                deduped.append(ev)
            all_evaluated[brief_id] = deduped

        if cross_cutting:
            _print(f"  [dim]Deduplicated {len(cross_cutting)} repos appearing in multiple sub-problems[/dim]")

        # 7. Build report
        if progress:
            with _make_spinner() as p:
                p.add_task("Generating report...")
                subproblem_reports = _build_subproblem_reports(all_evaluated, all_briefs)
        else:
            subproblem_reports = _build_subproblem_reports(all_evaluated, all_briefs)

        total_results = sum(len(sp.recommended) for sp in subproblem_reports)
        _print(f"\n[bold green]Done![/bold green] Found {total_results} recommended repos across {len(subproblem_reports)} sub-problems.")

        # Collect token usage from the LLM client
        usage = llm.get_usage()
        token_usage = TokenUsageSummary(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            total_cost=usage.total_cost,
            model=usage.model,
        )

        return ScoutReport(
            project_understanding=f"Searching for implementations related to: {description}",
            subproblems=subproblem_reports,
            unexpected_findings=all_observations,
            gaps=all_gaps,
            token_usage=token_usage,
        )

    finally:
        await gh.close()


def _build_subproblem_reports(
    all_evaluated: dict[str, list[EvaluatedResult]],
    all_briefs: dict[str, object],
) -> list[SubproblemReport]:
    """Build the list of SubproblemReport from evaluated results."""
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
    return subproblem_reports
