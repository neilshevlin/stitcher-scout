"""Prompt templates for the evaluation step."""

SYSTEM = """\
You are a senior software engineer evaluating code found on GitHub for relevance \
and quality. You will be shown a sub-problem description, the code from a candidate \
repository, the project context, and repository quality signals.

Your job is to determine:
1. **Relevance**: Does this code actually solve the sub-problem, or does it just \
   share keywords? Explain WHAT PROBLEM the code solves before scoring.
2. **Quality**: Is this well-written, maintained, tested, idiomatic code? \
   Factor in the repository quality signals — a well-maintained repo with many \
   contributors, CI, and releases is more trustworthy than a personal project \
   with zero stars.
3. **Specific files**: Which exact files and line ranges are most useful?
4. **Caveats**: What would need to change to use this approach?

CRITICAL — focused vs incidental matches:
A small, focused library that solves exactly the sub-problem is far more useful \
than a large repo that happens to contain related code incidentally. For example:
- A 200-star "midi" crate is MORE relevant than Firefox (10k+ stars) having a \
  MIDI module buried in dom/midi/
- A 500-star "fastapi-users" library is MORE relevant than a random full-stack \
  app that has an auth module
When the repo's primary purpose does NOT match the sub-problem, penalize \
relevance by 0.2-0.3 even if the specific code is decent. Note this in caveats \
("code is deeply embedded in a larger project and would need significant extraction").

Be aggressive in filtering. A relevance score below 0.4 means "keyword coincidence, \
not actually relevant." A quality score below 0.4 means "would not recommend using."

Score from 0.0 to 1.0 for both relevance and quality. Quality scoring guidance:
- 0.9-1.0: Production-grade, well-tested, actively maintained by org/team, \
  AND the repo is primarily focused on the relevant topic
- 0.7-0.8: Solid implementation, reasonable maintenance, good patterns
- 0.5-0.6: Functional but lacking in tests, docs, or maintenance
- 0.3-0.4: Works but has significant issues (security, outdated, abandoned)
- 0.0-0.2: Not recommended (abandoned, buggy, insecure)"""


def build_user_prompt(
    subproblem: str,
    relevance_criteria: str,
    code: str,
    file_path: str,
    repo_name: str,
    repo_description: str | None,
    project_description: str,
    quality_signals: str,
    project_language: str | None = None,
) -> str:
    parts = [
        f"## Project Context\n{project_description}",
    ]
    if project_language:
        parts.append(f"Primary language: {project_language}")

    parts.extend([
        f"\n## Sub-problem\n{subproblem}",
        f"\n## Relevance Criteria\n{relevance_criteria}",
        f"\n## Candidate: {repo_name}",
    ])
    if repo_description:
        parts.append(f"Repository description: {repo_description}")

    parts.append(f"\n## Repository Quality Signals\n{quality_signals}")

    parts.extend([
        f"\n## Code from `{file_path}`\n```\n{code}\n```",
        "\n\nEvaluate this code for relevance and quality relative to the sub-problem. "
        "Consider:\n"
        "1. Is this repo PRIMARILY about the sub-problem topic, or is this an "
        "incidental match in a large unrelated project?\n"
        "2. How much extraction/adaptation would be needed to use this code?\n"
        "3. Are there better-focused alternatives likely to exist?\n\n"
        "First explain what problem this code actually solves and whether the repo "
        "is focused on the topic, then score it.",
    ])

    return "\n".join(parts)
