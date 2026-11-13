# Batch research mode

Read this reference when the user requests more than 50 accepted companies or explicitly asks for resumable, multi-batch research.

## What stays unchanged

- Every accepted company still needs an AI target-fit recommendation of `accepted` plus verified product, buyer-role, and target-market evidence. Never promote `review` or `rejected` because evidence is complete.
- Each company still receives at most five page fetches.
- Static HTTP remains first; Playwright is fallback only.
- Robots guidance, delays, public-data boundaries, and no-CAPTCHA-bypass rules remain in force.
- A larger target never permits weaker evidence.

## Campaign settings

Set `research_mode` to `batch`. The default batch size is 50. For a target of 500 accepted companies, recommend a candidate ceiling of 2,500 unless the user chooses another limit.

```json
{
  "research_mode": "batch",
  "target_accepted": 500,
  "max_candidates": 2500,
  "batch_size": 50,
  "max_pages_per_company": 5
}
```

Batch mode supports at most 1,000 accepted companies, 5,000 checked candidates, and 100 candidates per batch. Split larger projects by market or buyer type.

## Python command

Use the project virtual-environment Python throughout one run.

- macOS: `.venv/bin/python`
- Windows PowerShell: `.\.venv\Scripts\python.exe`

The examples below use `<python>` as a placeholder for the appropriate command.

## Start or resume a run

Create one run directory and keep using it for the entire campaign.

```text
<python> skills/verifying-sales-leads/scripts/manage_batches.py init \
  --campaign campaign.json \
  --run-dir runs/<timestamp>
```

If the directory is already initialized with the same campaign, `init` is safe. If it contains a different campaign, the command stops instead of overwriting it.

At the start of every new conversation or after an interruption, read the current state:

```text
<python> skills/verifying-sales-leads/scripts/manage_batches.py status \
  --run-dir runs/<timestamp>
```

Follow `next_action` in the returned JSON. Do not rely on conversation memory for progress.

## Discovery and global deduplication

Discover candidates with several localized queries. Save official candidate URLs, discovery queries, and search-result source URLs as a JSON array. Add each discovery group to the run:

```text
<python> skills/verifying-sales-leads/scripts/manage_batches.py add-candidates \
  --run-dir runs/<timestamp> \
  --input discovery-001.json
```

The SQLite ledger deduplicates all discoveries by official domain across every batch. A company that is queued, in progress, or complete is never added again.

### Bulk discovery from OpenStreetMap

Outside the US, and for any storefront buyer type, read [discovery-methods.md](discovery-methods.md) first: it lists the `--preset` names, non-US areas, the mirror fallback, and `add-candidates --priority` for checking likely buyers first.

For storefront buyer types (cafes, tea shops, roasters, bakeries, restaurants, supermarkets), web search yields only a few new companies per query. Import places that list a website from OpenStreetMap instead, one area (a US state or another ISO 3166-2 region) per Overpass request:

```text
<python> skills/verifying-sales-leads/scripts/import_osm.py \
  --tag amenity=cafe --tag shop=tea --tag shop=coffee \
  --all-us-states \
  --exclude-candidates runs/<timestamp> \
  --raw-dir runs/<timestamp>/osm-raw \
  --output runs/<timestamp>/discovery-osm-cafe.json
```

Each item records the Overpass query and the OSM element URL as discovery provenance. Chain locations collapse to one company homepage (`osm_locations` counts them); social profiles, link hubs, ordering platforms, marketplaces, shared hosting tenants, and `.edu`/`.gov` sites are skipped. OSM is discovery only: every imported company is still crawled and needs on-site evidence. Keep the default pause between states and do not run parallel imports against the public Overpass server. Brands, wholesalers, and manufacturers are rarely mapped; find them with web search or the country-targeted `search_web.py` (see [discovery-methods.md](discovery-methods.md)).

## Process one batch

Ask the ledger for work:

```text
<python> skills/verifying-sales-leads/scripts/manage_batches.py next-batch \
  --run-dir runs/<timestamp>
```

Possible statuses:

- `batch_created`: process the returned candidates file.
- `resume_open_batch`: finish that existing batch; do not create or search a replacement batch.
- `needs_candidates`: run more discovery queries, add candidates, and ask again.
- `finished`: stop. Report whether the target or candidate ceiling ended the run.

Use the returned `candidates_file` with `crawl_candidates.py`. Save crawls and assessments inside the same numbered batch directory. Assess every candidate in the batch, including inaccessible and unsuitable sites.

```text
<python> skills/verifying-sales-leads/scripts/crawl_candidates.py \
  --campaign runs/<timestamp>/campaign.json \
  --candidates runs/<timestamp>/batches/0001/candidates.json \
  --output runs/<timestamp>/batches/0001/crawls.json
```

Before AI assessment, run the deterministic pre-screen:

```text
<python> skills/verifying-sales-leads/scripts/prescreen.py screen \
  --campaign runs/<timestamp>/campaign.json \
  --crawls runs/<timestamp>/batches/0001/crawls.json \
  --output runs/<timestamp>/batches/0001/prescreen.json
```

Companies with no usable page, or with no campaign product keyword on any usable page, receive an automatic `review` assessment (no claims, every exclusion `unclear`). The pre-screen can only route a company to review; it never accepts. Only companies in `for_ai` need AI assessment; their keyword snippets are reading hints, and evidence must still be copied exactly from the crawl pages. Write the AI assessments for `for_ai` companies, then merge:

```text
<python> skills/verifying-sales-leads/scripts/prescreen.py merge \
  --crawls runs/<timestamp>/batches/0001/crawls.json \
  --prescreen runs/<timestamp>/batches/0001/prescreen.json \
  --assessments runs/<timestamp>/batches/0001/ai-assessments.json \
  --output runs/<timestamp>/batches/0001/assessments.json
```

Merge fails if any crawled company lacks an assessment, or if an AI assessment tries to accept an auto-reviewed company.

Prefer writing compact decisions and building the assessments with guardrails (no default exclusion reasons, page lookup, quote-specificity checks):

```text
<python> skills/verifying-sales-leads/scripts/build_assessments.py \
  --campaign runs/<timestamp>/campaign.json \
  --crawls runs/<timestamp>/batches/0001/crawls.json \
  --decisions runs/<timestamp>/batches/0001/decisions.json \
  --output runs/<timestamp>/batches/0001/ai-assessments.json
```

Before merging, dry-run the acceptance gate on the AI drafts and fix every reported excerpt or URL (or downgrade that company to `review`):

```text
<python> skills/verifying-sales-leads/scripts/check_assessments.py \
  --campaign runs/<timestamp>/campaign.json \
  --crawls runs/<timestamp>/batches/0001/crawls.json \
  --assessments runs/<timestamp>/batches/0001/ai-assessments.json
```

### Parallel assessment across runs

A run issues one open batch at a time. To assess in parallel, split the candidates into separate runs (for example by US region), give each run to its own assessor agent, and merge the runs' exported lists at the end with domain deduplication:

```text
<python> skills/verifying-sales-leads/scripts/merge_runs.py \
  --run-dir runs/<pilot> --run-dir runs/<group-a> --run-dir runs/<group-b> \
  --output-dir runs/<combined>
```

Only final `accepted` records are merged, first run wins on duplicates, and `merge-summary.json` lists duplicates and companies whose status differs between runs. Every agent follows the same rules and the same scripts; the deterministic gate is unchanged.

After writing `assessments.json`, complete the batch:

```text
<python> skills/verifying-sales-leads/scripts/manage_batches.py complete-batch \
  --run-dir runs/<timestamp> \
  --batch-id 1 \
  --crawls runs/<timestamp>/batches/0001/crawls.json \
  --assessments runs/<timestamp>/batches/0001/assessments.json
```

Completion is transactional: if URLs are missing, duplicated, or do not match the open batch, no partial results are committed. A successful completion refreshes cumulative `leads.csv`, `audit.json`, and `summary.json` in the run directory.

## Loop and stopping rules

After every completed batch:

1. Read the printed summary.
2. Stop if `target_met` or `max_candidates_reached` is true.
3. If `next_action` is `create_next_batch`, request the next batch.
4. If `next_action` is `discover_more_candidates`, diversify queries and add another discovery file.
5. Repeat without revisiting completed domains.

`leads.csv` contains accepted companies up to the requested target. `audit.json` contains every completed candidate, including review, rejected, and blocked records. Existing `human_verdict` and `human_notes` values are preserved when later batches refresh the CSV.

When the candidate ceiling is reached before the accepted target, stop and report the shortfall and status counts. Do not silently increase the ceiling or lower the acceptance gate.


## Precision audit of accepted records

Periodically (and before delivering a list) flag accepted records whose evidence or exclusion checks look weak, then have an assessor re-check the flagged ones. The audit is read-only; downgrades are applied explicitly.

```text
<python> skills/verifying-sales-leads/scripts/audit_accepted.py \
  --run-dir runs/<timestamp> --output runs/<timestamp>/audit-flags.json
```

## Re-judging completed batches after the definition changes

When the user changes the campaign's acceptance definition (for example `product_evidence` from `already_handles` to `can_use`), earlier review records were judged under the old definition. Re-run `prescreen.py screen` on the saved crawls, write fresh assessments for the companies to re-judge, and apply them per batch:

```text
<python> skills/verifying-sales-leads/scripts/manage_batches.py reassess \
  --run-dir runs/<timestamp> --batch-id 3 \
  --crawls runs/<timestamp>/batches/0003/crawls.json \
  --assessments runs/<timestamp>/batches/0003/reassess-assessments.json
```

The same deterministic gate applies, duplicates of an already accepted canonical site stay in review, and each record keeps its previous status in `reassessment_history`. Never use reassess to override the gate under an unchanged definition. To lower a single record, use `downgrade --decisions` (optionally with `batch_id`).
