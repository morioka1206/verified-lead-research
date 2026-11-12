# Model delegation

When the client can run subagents on a smaller model (for example Claude Code), split the work so the main conversation keeps only the decisions that need it. Clients without subagents follow the normal workflow in the main conversation; results and gates are identical either way.

| Step | Who | Suggested model |
|---|---|---|
| Intake, final brief, judgment rules, borderline cases, final report | main conversation | the session's model |
| Search queries → candidate URLs | `lead-scout` agent | Haiku |
| Normalize, crawl, pre-screen, build, check, finalize | scripts | — |
| Reading crawled pages → decisions | `lead-assessor` agents in parallel | Sonnet |
| Spot-check accepted records, resolve `review` patterns | main conversation | the session's model |

In Claude Code the agents ship with this repository: as a plugin they are `verified-lead-research:lead-scout` and `verified-lead-research:lead-assessor`; in a session opened in the repository they are `lead-scout` and `lead-assessor`. If neither is available, use a general-purpose subagent with the model set explicitly and paste the agent file's instructions (`agents/*.md` at the repository root) into its prompt.

Delegation never changes the acceptance gate. Assessors only write decisions; `build_assessments.py`, `check_assessments.py`, and the finalizer still verify every quote against its page and every exclusion check, so a weaker assessment can only fall to `review`, never become `accepted`.

## Discovery

Write the localized queries yourself, then give each `lead-scout` a few queries, the campaign's `excluded_types`, and its own output file, e.g. `runs/<run>/raw-candidates-1.json`. Combine the files as one JSON array and run `prepare_candidates.py`, which normalizes and deduplicates. Glance at the list before crawling; drop obvious non-companies.

## Assessment

After crawling (standard mode: `runs/<run>/crawl.json`; batch mode: the batch's crawl file):

```bash
<python> scripts/prescreen.py screen --campaign <campaign> --crawls <crawl> --output <dir>/prescreen.json
<python> scripts/prescreen.py split --prescreen <dir>/prescreen.json --parts <n> --output-dir <dir>
```

Use about one part per 4–8 companies, at most 5 parts at a time. Start one `lead-assessor` per part in parallel and give it the paths to the campaign, the crawl file, its `for-ai-partK.json`, its output `decisions-partK.json`, the project Python, and the absolute `scripts/` directory. Companies are addressed by crawl `index`, so URL redirects (`example.com` → `www.example.com`) cannot break the join.

When all parts are back:

```bash
<python> scripts/build_assessments.py --campaign <campaign> --crawls <crawl> \
  --decisions <dir>/decisions-part1.json --decisions <dir>/decisions-part2.json \
  --output <dir>/ai-assessments.json
<python> scripts/check_assessments.py --campaign <campaign> --crawls <crawl> --assessments <dir>/ai-assessments.json
<python> scripts/prescreen.py merge --crawls <crawl> --prescreen <dir>/prescreen.json \
  --assessments <dir>/ai-assessments.json --output <dir>/assessments.json
```

Then finalize (standard mode) or `complete-batch` (batch mode) with `assessments.json` as usual.

Before reporting, read every `accepted` record's three quotes and the `uncertainties` of the `review` records yourself. If assessors applied a judgment rule inconsistently (for example one subsidiary of a Japanese producer accepted and another held), do not resolve it silently: lower the inconsistent record to `review` or ask the user which reading to apply, then re-run the affected part.
