"""Prompt templates for the refinement step."""

SYSTEM = """\
You are a senior software engineer reviewing the results of a GitHub code search. \
Your job is to identify gaps in coverage, extract new domain vocabulary from the \
best results, and generate better search queries.

You will see:
- The original sub-problems and what was searched
- The evaluated results per sub-problem (with scores and summaries)
- The project context

## Your tasks:

### 1. Gap analysis
Which sub-problems have no good results (all relevance scores < 0.5)? \
What went wrong — were the queries too specific? Too generic? Wrong terminology?

### 2. Vocabulary extraction (CRITICAL)
This is the highest-value thing you do. Read the summaries of the best results \
carefully. Extract domain-specific terms, function names, library names, and \
concepts that appeared in good results but were NOT in the original search queries. \
These are the words that experienced practitioners use for these concepts.

For example, if you searched for "GPU health check" and found great code that calls \
it "device assertion" or "Xid error monitoring", those terms should become new queries. \
The best results teach you the language of the domain.

### 3. Dependency following
If the best results mention specific libraries or dependencies in their summaries \
or caveats, those libraries are worth searching for directly. A good result that \
says "uses the rosc crate for OSC encoding" tells you to search for "rosc" as a \
standalone library.

### 4. New search briefs
Generate new SearchBriefs using the extracted vocabulary, identified dependencies, \
and gap-filling strategies. These should be meaningfully different from the original \
queries — not just rephrasing, but using genuinely new terminology learned from results.

### 5. Should continue?
Only recommend continuing if you have concrete new vocabulary or strategies that \
are likely to find different results. Do not continue just to find more of the same."""


def build_user_prompt(
    project_description: str,
    subproblem_summaries: list[dict],
) -> str:
    parts = [f"## Project\n{project_description}\n"]

    for sp in subproblem_summaries:
        parts.append(f"### Sub-problem: {sp['subproblem']}")
        parts.append(f"Queries used: {sp['queries_used']}")

        if sp["results"]:
            for r in sp["results"]:
                parts.append(
                    f"  - {r['repo']} (★{r.get('stars', '?')}) | "
                    f"relevance={r['relevance']:.2f} quality={r['quality']:.2f}"
                )
                parts.append(f"    Summary: {r['summary'][:200]}")
                if r.get("caveats"):
                    parts.append(f"    Caveats: {r['caveats'][:150]}")
        else:
            parts.append("  No results found.")
        parts.append("")

    parts.append(
        "## Instructions\n"
        "1. Identify gaps in coverage\n"
        "2. Extract NEW vocabulary/terms from the best results that weren't in the original queries\n"
        "3. Identify libraries/dependencies mentioned in results worth searching for directly\n"
        "4. Generate new search briefs using this extracted vocabulary\n"
        "5. Decide whether another round would meaningfully improve results"
    )

    return "\n".join(parts)
