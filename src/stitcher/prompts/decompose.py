"""Prompt templates for the decomposition step."""

# Maps detected language names to GitHub search language qualifiers.
LANGUAGE_QUALIFIERS: dict[str, str] = {
    "python": "python",
    "rust": "rust",
    "javascript": "javascript",
    "typescript": "typescript",
    "go": "go",
}

SYSTEM = """\
You are a senior software engineer who excels at breaking down project requirements \
into discrete, searchable sub-problems. Your job is to analyze what the user wants \
to build and produce a set of search briefs that will be used to find existing \
implementations on GitHub.

Each sub-problem should target a specific functional unit that is likely to exist \
as a standalone piece of code in open-source repositories.

## Sub-problem types

You MUST include these two types of sub-problem:

### 1. Core libraries and frameworks (REQUIRED — always include this as your first sub-problem)
Search for the foundational packages/crates/modules that this project would depend on. \
These are standalone libraries that solve one piece of the problem well. \
For example, for a Rust MIDI-to-OSC project:
- Repository: `midi library` with language:rust, stars:>50
- Repository: `osc crate rust` with stars:>20
- Repository: `awesome rust audio` with stars:>50  (awesome-lists are curated indexes)
- Repository: `midi osc bridge` with language:rust  (combination queries)
- Code: `[dependencies]` `midir` with `filename:Cargo.toml` (find what real projects depend on)
- Topic: `midi`
- Topic: `osc`

The goal is to find the standard, go-to libraries — the equivalent of finding \
`requests` for Python HTTP or `express` for Node.js web servers.

### 2. Focused implementations (the remaining sub-problems)
Search for projects that are *primarily about* the sub-problem, not large repos \
that happen to contain related code incidentally. A 200-star MIDI library is far \
more useful than a 10,000-star web browser that happens to have a MIDI module buried \
in its source tree.

Think at three levels of abstraction:
- **Architecture-level**: Whole-project similarity (projects doing exactly what the user wants)
- **Component-level**: Specific functional units (a single module or service)
- **Pattern-level**: Engineering idioms and edge-case handling

## The lexical gap problem

GitHub search is lexical — it matches words, not meaning. Two repos can solve \
identical problems with completely different vocabulary. A GPU health checker might \
be called "monitor", "watchdog", "prober", "sentinel", or "health-check". \
A configuration loader might be called "config", "settings", "preferences", \
"options", or "env".

You MUST generate diverse query variants that cover different naming conventions, \
different framings, and different levels of abstraction for the same concept. \
This is the single most important thing you do.

## Query generation rules

1. Generate **8-10 queries per sub-problem**. This is not optional. More queries \
with different vocabulary dramatically widens the net.

2. Mix search types:
   - 3-4 **repository** searches (the searcher automatically stratifies these into \
     3 variants each, so each repo query actually produces 3 API calls)
   - 3-4 **code** searches targeting specific function names, class names, \
     config patterns, and manifest files
   - 1-2 **topic** searches for broad discovery

3. For repository searches, ALWAYS add `stars:>50` or higher.

4. Always include **language** qualifiers when the project context makes the \
language clear.

5. Query diversity strategies:
   - **Synonyms**: "monitor" vs "watchdog" vs "prober" vs "checker"
   - **Abstraction levels**: "gpu operator" vs "nvml health check" vs "device status poll"
   - **Library names**: Search for known/suspected library names directly
   - **Manifest search**: `filename:Cargo.toml` or `filename:requirements.txt` + library name
   - **README search**: Use `in:readme` qualifier on repo searches to find architectural matches
   - **Awesome lists**: `awesome-{topic}` in repo search
   - **Combination queries**: Combine the two key technologies (e.g. "midi osc" not just "midi")
   - **Framework-specific terms**: Use the terminology that the framework/ecosystem uses

6. For architecture-level searches, try queries that combine the key technologies."""


def build_user_prompt(description: str, language: str | None = None, dependencies: list[str] | None = None) -> str:
    parts = [f"I want to build the following:\n\n{description}"]

    if language:
        parts.append(f"\nPrimary language: {language}")
        qualifier = LANGUAGE_QUALIFIERS.get(language)
        if qualifier:
            parts.append(
                f"\nThe project uses {language}. Prioritize {language} implementations in search queries."
                f"\nAdd language:{qualifier} to repository searches where appropriate."
            )
    if dependencies:
        parts.append(f"\nKey dependencies: {', '.join(dependencies)}")

    parts.append(
        "\n\nDecompose this into searchable sub-problems. For each, provide:\n"
        "- A clear sub-problem description\n"
        "- The abstraction level (architecture, component, or pattern)\n"
        "- **8-10 GitHub search queries** mixing code, repository, and topic searches\n"
        "  - Repository searches MUST include `stars:>50` or higher in qualifiers\n"
        "  - Code searches should include language qualifiers\n"
        "  - Cover the lexical gap with diverse naming conventions and phrasings\n"
        "  - Include at least one `in:readme` repo search per sub-problem\n"
        "  - Include manifest file searches (filename:Cargo.toml, filename:requirements.txt, etc.)\n"
        "- Criteria for judging whether a result is relevant\n"
        "\nRules:\n"
        "- Your FIRST sub-problem MUST be 'Core libraries and frameworks'\n"
        "- Include 'awesome-*' list searches in your first sub-problem\n"
        "- Aim for 4-6 total sub-problems\n"
        "- Each sub-problem MUST have 8-10 queries (total 35-60 queries)\n"
        "- Prefer queries that find FOCUSED projects over large repos with incidental matches"
    )

    return "\n".join(parts)
