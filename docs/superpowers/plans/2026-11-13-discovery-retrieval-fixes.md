# Discovery and retrieval fixes

> **For agentic workers:** Use superpowers:executing-plans; implement and test each task inline, then obtain one independent whole-change review.

**Goal:** Correct four reproduced omissions in remote baseline `68beac0` without changing acceptance rules or research data.

**Architecture:** Keep the shared Python implementation. Separate visible HTML text from appended structured evidence for rendering decisions; narrow cookie-policy filtering; validate Overpass payloads before success; reuse the existing tenant-aware company-root normalizer.

**Tech Stack:** Python unittest, Playwright 1.63.0, Chromium, SQLite (unchanged).

**Spec:** User approved the preceding four-finding review and recommended fix-first approach on 2026-11-13. No new discovery scope, paid API use, research-list writes, remote publication, or replacement of the dirty original checkout is authorized here.

## Constraints and choices

- Work from latest origin/main in an isolated worktree; retain original `import_osm.py` edits and all runs untouched.
- Prefer bounded corrections over a rewrite or a rollback that discards Claude cloud improvements.
- AI recommendation, three literal claims, all exclusion checks, five-page budget and robots handling remain unchanged.
- Treat US-only search as a possible environment-specific observation, not a proven platform-wide result restriction.
- Tests precede production changes. Existing baseline: 122 tests pass including local browser tests.

## Review focus

- JSON-LD addresses plus an empty JavaScript shell must still render; long visible pages must not render unnecessarily.
- Cookie products and menus remain discoverable; policy pages still do not occupy evidence slots.
- Overpass runtime remarks, malformed results, partial results, and valid empty regions have distinct success/failure behavior.
- Supported shared tenants preserve identity; provider homepages and unsupported shared hosting remain excluded.
- Both clients share the same gates; keyword prescreen must preserve `can_use` intent.

## Tasks

### 1. Retrieval regressions

Files: `tests/test_discovery_regressions.py`, `skills/verifying-sales-leads/scripts/leadlib.py`.

- [x] Add rendering/visible-content and cookie-product/policy regressions; observe failure.
- [x] Keep visible text separate for shell detection, retaining structured addresses in evidence text.
- [x] Filter cookie policy destinations specifically instead of the word cookie anywhere.
- [x] Run focused tests and full suite.

### 2. Discovery regressions

Files: same test file; `skills/verifying-sales-leads/scripts/import_osm.py`.

- [x] Add payload-error retry/mirror/empty-region and shared-tenant tests; observe failure.
- [x] Reject incomplete Overpass responses before returning success or saving area completion.
- [x] Use `company_root_url`, excluding shared provider roots that have no tenant scope.
- [x] Run focused tests and full suite.

### 3. Documentation and independent review

Files: `docs/cloud-claude-code.md`, discovery/model delegation references, `STATUS.md`.

- [x] Clarify environment observations versus product-wide search scope and the limits of literal evidence validation.
- [x] Update plain-language status; run whole suite and Skill validation (135 tests, valid Skill).
- [x] Obtain independent review, resolve important findings with RED→GREEN, record limitations.
- [x] Preserve completed work in a local branch; no push, main merge, or live Skill migration without resolving the original dirty checkout first.
