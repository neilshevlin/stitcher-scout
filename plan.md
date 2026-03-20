# GitHub Code Scout — V1 Build Plan

*An agent that finds real, working code on GitHub relevant to your project, so you build on proven implementations instead of generating from scratch.*

---

## What V1 Does

You describe what you want to build. The agent searches GitHub, finds the best existing implementations of each sub-problem, evaluates them for quality and relevance, and presents a structured report with specific files and functions to look at.

V1 does not stitch code together, adapt code to your project, or write any code itself. It is a research and curation tool. The output is a document you read, not code you run.

## What V1 Does Not Do

- Automatic code adaptation or stitching
- Persistent indexing of GitHub (uses the API on the fly)
- Licence compliance checking (flag for v2)
- Integration with your editor or IDE
- Multi-repo synthesis into working code

---

## Architecture Overview

The system is a CLI tool (or web app) backed by an LLM agent loop. The user provides a project description, optionally points at an existing repo, and the agent runs a search-evaluate-refine loop against the GitHub API, producing a structured markdown report.

### Components

**Input parser.** Takes the user's natural language description and, optionally, a path or URL to their existing repo. If a repo is provided, it extracts: primary language, key dependencies, framework conventions, and directory structure. This becomes the *project context* that shapes all downstream searches.

**Decomposer (LLM).** Breaks the user's request into discrete, searchable sub-problems at three levels of abstraction: architecture-level (whole-project similarity), component-level (specific functional units), and pattern-level (engineering idioms and edge-case handling). Each sub-problem gets a search brief: a description, suggested search queries, expected result type (repo, file, or function), and relevance criteria.

**Search executor.** For each search brief, runs multiple queries against the GitHub API using different strategies — code search, repository search, topic search, and optionally issue/discussion search. Over-fetches deliberately; filtering happens later.

**Evaluator (LLM).** For each candidate result, reads the actual code (not just the README) and judges: is this genuinely relevant or a keyword coincidence? Is this code good — maintained, tested, idiomatic? What specific files and line ranges matter? Assigns a quality score and a relevance score. Filters aggressively.

**Refiner (LLM).** After the first pass of evaluation, identifies gaps ("I found nothing good for sub-problem 3"), surprises ("every good result also handles X, which the user didn't mention"), and refinement opportunities ("the results suggest a better decomposition"). Generates new search briefs and loops back to the search executor. Runs for a configurable number of iterations or until coverage is satisfactory.

**Presenter.** Takes the evaluated, filtered results and produces a structured markdown report organised by sub-problem. Each recommended code fragment includes: repo name and URL, quality signals (stars, last commit, CI status, test presence), specific file path and line range, a brief explanation of the approach, and caveats or adaptation notes.

---

## The Agent Loop in Detail

```
User input + optional repo context
        │
        ▼
┌─────────────────────┐
│  1. Parse context    │
│     (repo + desc)    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  2. Decompose into  │◄──────────────────┐
│     search briefs   │                   │
└────────┬────────────┘                   │
         │                                │
         ▼                                │
┌─────────────────────┐                   │
│  3. Execute searches│                   │
│     (GitHub API)    │                   │
└────────┬────────────┘                   │
         │                                │
         ▼                                │
┌─────────────────────┐                   │
│  4. Evaluate results│                   │
│     (read code,     │                   │
│      score, filter) │                   │
└────────┬────────────┘                   │
         │                                │
         ▼                                │
┌─────────────────────┐    gaps/new       │
│  5. Refine          │────questions──────┘
│     (gap analysis,  │
│      new searches)  │
└────────┬────────────┘
         │ coverage OK
         ▼
┌─────────────────────┐
│  6. Present report  │
└─────────────────────┘
```

### Loop termination

The refine step decides whether to loop again based on three criteria: coverage (do we have at least one good result for each sub-problem?), iteration budget (default max 3 refinement loops), and diminishing returns (did the last loop surface anything meaningfully new?). In fast mode, the loop runs once with no refinement. In deep mode, it runs up to the budget.

---

## Search Strategy

### GitHub API endpoints used

| Endpoint | Purpose | When to use |
|----------|---------|-------------|
| `GET /search/code` | Find specific functions, patterns, config | Component and pattern-level searches |
| `GET /search/repositories` | Find whole projects doing similar things | Architecture-level searches |
| `GET /search/topics` | Find repos tagged with relevant topics | Broad discovery |
| `GET /repos/{owner}/{repo}/contents` | Read specific files from a candidate repo | Evaluation step |
| `GET /repos/{owner}/{repo}` | Get repo metadata (stars, last push, etc.) | Quality scoring |

### Query generation

The decomposer generates multiple query variants per sub-problem. For example, for "NVML health check polling in Go":

- Code search: `language:go nvml health` , `language:go gpu monitor poll`
- Repo search: `gpu health monitor language:go`, `nvml kubernetes operator`
- Topic search: `gpu-monitoring`, `nvml`, `kubernetes-gpu`

The key insight is that the same concept has many surface forms in code. A function that checks GPU health might be called `checkHealth`, `pollDeviceStatus`, `nvmlQuery`, or `runDiagnostics`. The LLM generates diverse queries to cover this lexical gap.

### Quality signals for scoring

| Signal | Weight | Source |
|--------|--------|--------|
| Stars | Medium | Repo metadata |
| Last commit < 6 months | High | Repo metadata |
| Has CI/CD config | High | File presence (`.github/workflows/`, `Jenkinsfile`, etc.) |
| Has tests in relevant area | High | Code search for `_test.go`, `test_*.py`, etc. near the relevant code |
| Not archived | Required | Repo metadata |
| Clear README with description | Medium | Repo contents |
| Multiple contributors | Low | Repo metadata |

These signals are heuristics, not gospel. The LLM evaluator uses them as inputs alongside its own judgment about code quality from reading the actual source.

---

## Output Format

The report is structured markdown, organised by sub-problem.

```markdown
# Code Scout Report: GPU Node Health Operator

## Project Understanding
[Brief restatement of what the user is building, the inferred tech stack,
and the sub-problems identified]

## Sub-problem 1: Kubernetes Operator Scaffold
[Why this is a sub-problem, what the agent searched for]

### Recommended: gpu-operator by NVIDIA (★ 1.2k, last commit 3 days ago)
- **File:** `controllers/node_controller.go`, lines 45-120
- **What it does:** Reconciliation loop watching GPU node labels, 
  handles add/update/delete with controller-runtime.
- **Why this one:** Production-grade, uses current controller-runtime API, 
  comprehensive error handling.
- **Caveat:** Tightly coupled to NVIDIA's CRD schema — you'd need to 
  extract the reconciliation pattern and adapt the CRD.
- **Link:** https://github.com/...

### Alternative: kube-gpu-watcher by $someone (★ 340, last commit 2 months ago)
- **File:** ...
- ...

## Sub-problem 2: GPU Health Detection via NVML
...

## Unexpected Findings
[Things the agent noticed across results that the user didn't ask about
but probably should consider — e.g. "most GPU operators also implement
MIG partition management, which you may want to plan for"]

## Gaps
[Sub-problems where the agent couldn't find good implementations,
with notes on why and what the user might do instead]
```

---

## Tech Stack for V1

**Language:** Python. Fast to iterate, good GitHub API libraries, easy LLM integration.

**Key dependencies:**
- `PyGithub` or raw `httpx` for GitHub API access
- `anthropic` or `openai` SDK for LLM calls (decomposition, evaluation, refinement)
- `click` or `typer` for CLI
- `rich` for terminal output while the agent runs

**LLM usage:** The agent makes LLM calls at three points — decomposition, evaluation, and refinement. Decomposition and refinement are single calls. Evaluation may be many calls (one per candidate result worth reading), so this is where cost and latency concentrate. V1 should batch evaluation where possible and set a cap on candidates evaluated per sub-problem (e.g., top 5 by heuristic quality signals).

**GitHub API rate limits:** Authenticated requests get 30 search requests per minute and 5,000 general requests per hour. A typical deep-mode run might use 20-40 search requests and 50-100 content fetches, well within limits. Fast mode stays under 10 search requests.

**Configuration:**
- GitHub personal access token (required)
- LLM API key (required)
- Mode: `fast` or `deep` (default: fast)
- Optional: path to existing repo for context

---

## Implementation Phases

### Phase 1: Walking skeleton (1-2 days)

Build the simplest possible end-to-end flow: hardcode a single sub-problem, run one GitHub code search query, fetch the top result, and format it as markdown. No LLM, no loop, no evaluation. The goal is to prove the GitHub API integration works and the output format feels right.

### Phase 2: LLM decomposition (1-2 days)

Add the decomposer — take natural language input, use an LLM to generate search briefs, and run the searches. Still no evaluation; just present raw results ranked by heuristic quality signals. This is the point where you can start testing whether the decomposition produces good searches.

### Phase 3: LLM evaluation (2-3 days)

Add the evaluator — for each candidate, fetch the relevant code, pass it to an LLM with the project context and relevance criteria, get back a score and summary. Filter and rank. This is the hardest step and the one most likely to need prompt iteration. The evaluation prompt needs to distinguish "this code mentions the same keywords" from "this code solves the same problem."

### Phase 4: Refinement loop (1-2 days)

Add the refiner — after evaluation, identify gaps and generate new search briefs. Wire up the loop with termination conditions. Test on a few different project descriptions to see if refinement actually improves results or just adds noise.

### Phase 5: Project context parsing (1 day)

Add the ability to point the agent at an existing repo (local path or GitHub URL) and extract stack, dependencies, and conventions. Use this to improve search queries (e.g., filter by language) and evaluation (e.g., penalise results in a different framework).

### Phase 6: Polish (1-2 days)

CLI UX, progress output while the agent runs, error handling for API failures and rate limits, configurable depth, and clean report formatting.

**Total estimated time: 7-12 days to a usable v1.**

---

## Open Questions

**How much code should the evaluator read?** Reading entire files is expensive (tokens and latency). Reading only the function signature misses context. The pragmatic middle ground is probably: read the file, but truncate at ~500 lines, and rely on the LLM to focus on the relevant section.

**Should the report include code snippets?** Embedding code directly in the report makes it self-contained but raises licence questions. The safer v1 approach is to include file paths and line ranges with links, and let the user read the code on GitHub. A "show code" expansion option could be a v1.5 addition.

**What model for evaluation?** Evaluation is the most token-heavy step and needs good code understanding. Sonnet is probably the right trade-off for v1 — fast enough for batch evaluation, good enough at code comprehension. Opus for decomposition and refinement where the calls are fewer but the reasoning matters more.

**How to handle monorepos and very large repos?** Some of the best code lives in massive repos where GitHub code search returns results from irrelevant subdirectories. The evaluator needs to understand repo structure well enough to navigate this, which may require fetching the directory tree first.

**Is there a web UI play?** The CLI is the right v1 form factor for developer users. But the report format would also work well as a web page with expandable sections and embedded code viewers. Worth considering for v2 if the core agent works.