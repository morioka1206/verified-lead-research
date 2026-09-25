# Batch research mode

Read this reference when the user requests more than 30 accepted companies or explicitly asks for resumable, multi-batch research.

## What stays unchanged

- Every accepted company still needs verified product, buyer-role, and target-market evidence.
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
