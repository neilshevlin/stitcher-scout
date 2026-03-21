# How It Works

Stitcher runs a multi-stage pipeline that combines GitHub's search API with LLM evaluation of actual source code. The goal is to find repos that are genuinely relevant to your problem — not just keyword matches, but code you could actually learn from or use.

## Pipeline overview

```
Description ──► Decompose ──► Search ──► Evaluate ──► Dedup ──► Report
                                  ▲          │
                                  │          ▼
                                  └── Refine ◄── (deep mode only)
```

### 1. Decompose

An LLM breaks your project description into discrete sub-problems. Each sub-problem gets 8-10 search queries designed to cover the "lexical gap" — the fact that different developers describe the same thing with different words.

For example, "GPU health monitoring" might generate queries for:
- `gpu health check` (direct)
- `device assertion monitoring` (NVIDIA terminology)
- `xid error` (specific error type)
- `awesome-gpu-monitoring` (awesome lists)
- `filename:Cargo.toml gpu` (dependency discovery)

The first sub-problem is always **"Core libraries and frameworks"** — the foundational packages your project would depend on. This catches the building blocks that more specific searches might miss.

### 2. Search

Each query is stratified into three variants to catch different types of repos:

- **Sort by stars** — finds the most popular implementations
- **Sort by recently updated** — finds actively maintained code
- **Mid-range stars (50-500)** — finds focused libraries that aren't famous but solve the problem well

This tripling means 8 queries per sub-problem become ~24 actual GitHub API calls, covering a wide range of the ecosystem.

Code searches and repository searches use different strategies. Repo-only qualifiers like `stars:>50` are automatically stripped from code searches where they'd be invalid.

### 3. Evaluate

This is where stitcher reads actual code, not just repo descriptions.

For each candidate repo, stitcher:

1. Fetches the directory tree
2. Identifies likely-relevant files
3. Reads the source code (up to 500 lines per file)
4. Sends the code + repo metadata to the LLM for evaluation

The LLM scores each repo on two dimensions:

**Relevance (0.0-1.0)** — Does this repo actually solve the sub-problem?
- A 200-star MIDI library scores higher than Firefox (which happens to contain some MIDI code)
- Below 0.4 means keyword coincidence, not genuine relevance

**Quality (0.0-1.0)** — Is the code worth using?
- Factors: code patterns, test coverage, documentation, maintenance activity
- Also considers repo signals: stars, CI, releases, contributors

The LLM also identifies specific files and line ranges to look at, and notes caveats about using the code.

### 4. Dependency following

After the first evaluation pass, stitcher reads dependency manifests (`Cargo.toml`, `requirements.txt`, `package.json`, `go.mod`, `pyproject.toml`) from the top-scored repos. It extracts library names, filters out common/generic dependencies (like `serde`, `pytest`, `lodash`), and searches for the remaining ones as standalone tools.

This catches foundational libraries that the top repos depend on but that wouldn't appear in a direct search for the project description.

### 5. Refine (deep mode)

In deep mode, stitcher runs additional passes. The refinement step:

1. **Gap analysis** — Which sub-problems still lack good results?
2. **Vocabulary extraction** — What domain-specific terms appear in the best results that weren't in the original queries? (e.g., searched for "GPU health check", found code calling it "device assertion")
3. **Dependency following** — Libraries mentioned in summaries or caveats
4. **New queries** — Generated using the extracted vocabulary
5. **Continue decision** — Only continues if there's genuinely new terminology to try

Each refinement loop feeds new vocabulary back into search, progressively covering more of the ecosystem. The default limit is 3 loops.

### 6. Cross-subproblem deduplication

After evaluation, stitcher detects repos that appear in multiple sub-problems. For each duplicate, it keeps only the highest-scored version and drops the others. Repos that span multiple sub-problems are flagged as "Swiss Army knife" repos in the Unexpected Findings section — these are often foundational libraries worth paying attention to.

### 7. Report

The final report groups results by sub-problem, sorted by combined relevance and quality scores. It includes:

- **Per-subproblem recommendations** — repository, scores, relevant files, caveats
- **Ecosystem map** — a table of all recommended repos showing which sub-problems each is relevant to, sorted by cross-cutting relevance
- **Patterns & Insights** — dominant language, common topics, license distribution, average repo age and activity level
- **Unexpected findings** — cross-cutting repos and other surprises
- **Gaps** — sub-problems where no good results were found
- **Cost summary** — total tokens used and estimated cost for the run

## Caching

Stitcher caches GitHub API responses locally using a SQLite-backed disk cache (via `diskcache`). This speeds up repeated searches and reduces GitHub API usage.

| Data type | TTL | Why |
|-----------|-----|-----|
| Search results | 1 hour | Repos change, new ones get published |
| Repo metadata (contributors, CI, releases) | 24 hours | Changes infrequently |
| File content | 7 days | Source code is stable |

The cache is stored at `~/.cache/stitcher-scout/` (override with `STITCHER_CACHE_DIR`). Clear it with `stitcher cache-clear`.

Install the cache optional dependency for caching: `pip install stitcher-scout[cache]`. Without it, caching is silently disabled.

## Research brief

The `--brief` flag generates a model-agnostic research brief alongside the normal report. The brief contains:

- Per-subproblem recommendations with install commands and GitHub file URLs
- A starter dependency manifest in your target language's format (requirements.txt, Cargo.toml, package.json, go.mod)
- Architecture notes derived from patterns across top repos
- Gaps and risks

This is designed to be consumed by any developer or AI agent as a starting point for implementation.

## Token usage and cost

Each report includes a cost summary showing prompt tokens, completion tokens, total tokens, and estimated cost. This uses litellm's cost estimation which covers all major providers. Use this to understand the cost of different search modes and model choices.

If cost calculation fails (e.g., unsupported model or litellm pricing data unavailable), the report shows "Estimated cost: unavailable" rather than a misleading $0.00.

## Quality scoring

Repos are scored on a weighted 0.0-1.0 scale using these signals:

| Signal | Weight | Scoring |
|--------|--------|---------|
| Stars | 20% | Log scale (10→0.3, 100→0.6, 1000→0.8, 10000→1.0) |
| Contributors | 15% | 1→0.1, 2→0.4, 3→0.6, 5→0.8, 10+→1.0 |
| Forks | 10% | Log scale |
| Recency | 10% | <30d→1.0, <90d→0.8, <180d→0.6, <1y→0.3, older→0.1 |
| CI/CD presence | 10% | Has workflows/CI config = 1.0 |
| Org-owned | 10% | Organization = 1.0, personal = 0.3 |
| Releases | 10% | 5+→1.0, 2+→0.7, 1→0.4, none→0.0 |
| License | 5% | Has license = 1.0 |
| Repo age | 5% | 3y+→1.0, 2y+→0.8, 1y+→0.6, 3m+→0.3, newer→0.1 |
| Not archived | 5% | Active = 1.0, archived = 0.0 |

## Focus scoring

Large popular repos often contain code for many things. A web browser might include MIDI support, but it's not a "MIDI library." The focus score (0.0-1.0) measures whether a repo is *primarily about* the search topic:

- **1.0** — Repo name contains search terms AND description matches (e.g., `org/midi-parser`)
- **0.8** — Name matches but description is partial
- **0.7** — Description matches but name doesn't
- **0.4** — Partial keyword match
- **0.1** — No terms appear in name, description, or topics

Before sending candidates to the (expensive) LLM evaluator, stitcher ranks them using a blend of **40% quality + 60% focus**. This ensures focused small libraries get evaluated before large unfocused repos.
