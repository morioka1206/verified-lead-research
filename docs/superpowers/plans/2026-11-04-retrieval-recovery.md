# Retrieval Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user chose in-place inline implementation and Astra/high final review.

**Goal:** Recover legitimate company websites without relaxing acceptance or safe fetching.
**Architecture:** Keep Python/Playwright, add a shared bounded browser launcher and a diagnostic CLI, improve static decoding and bounded link selection, and separate company identity from raw host identity. Preserve saved SQLite keys by deriving semantic duplicate keys from stored candidate URLs instead of migrating records.
**Tech Stack:** Python 3.12, existing pinned Playwright/Chromium, unittest.
**Spec:** docs/2026-11-04-retrieval-recovery-design.md (user approved scope and current-folder implementation).

## Global Constraints

- Maximum five pages per company; robots, public-IP, TLS and size checks remain.
- AI accepted + three verified claims + clear exclusions remains mandatory; no promotion of review/rejected.
- Do not modify completed research outputs or unrelated dirty files. No commit/push in this request.
- Reviewer: gpt-6-astra, high effort, fresh context.

## Review Focus

- Legacy SQLite domain keys must not create duplicate companies after the new key scheme.
- Shared-host links and redirects must not mix neighboring tenants' evidence or contacts.
- Frame/image links must remain bounded, same-company and robots-checked.
- Browser startup failures must be environment errors, not nonexistent companies or blocked access claims.
- HTTP error pages and corrupt encoding must not become valid evidence.

### Task 1: Browser diagnostics and normal Chromium

Files: leadlib.py, new scripts/check_browser.py, tests/test_retrieval_recovery.py, tests/test_playwright_dynamic.py.
Interfaces: launch_browser(playwright, timeout: float) -> Browser; browser_diagnostic(timeout: float) -> dict. Default same pinned normal Chromium; VLR_BROWSER_CHANNEL can explicitly select chromium or headless-shell.
- [x] Add and run failing tests for environment-error classification, diagnostic success/failure, real JavaScript rendering and refusal of error-page evidence.
- [x] Implement bounded launch and diagnostic CLI; reuse launch helper in dynamic test.
- [x] Run focused tests and full suite, record outcomes.

### Task 2: Bounded company-information retrieval

Files: leadlib.py, crawl_candidates.py, tests/test_retrieval_recovery.py.
Interfaces: existing parse_site/priority_links/crawl_company contracts retained; parsed frame links and image alt text become observed links, Japanese location/business groups are recognized.
- [x] Add/run failing fixtures: Japanese nested index + late detail within five pages, frame and image links, Shift_JIS decoding. Retain HTTP-header charset precedence and run existing size/private/robots regressions; add actual robots-denied iframe request verification.
- [x] Implement decoding and bounded prioritized traversal. Limit attempts, not only successful pages; canonicalize final URLs and deduplicate redirects. Add locations to general page priority while retaining hospitality behavior.
- [x] Run focused and whole-suite tests.

### Task 3: Shared-host company identity and documentation

Files: leadlib.py, prepare_candidates.py, manage_batches.py, tests/test_retrieval_recovery.py, SKILL.md, README.md, GUIDE.html, STATUS.md.
Interfaces: company_key(url: str) -> str and company_root_url(url: str) -> str. domain_key remains raw-host API. Scope known shared providers (NNS/FRUITS tilde paths, r.goope.jp, yamanashi-machitsukuri.jp); ordinary sites retain host-level dedupe.
- [x] Add/run failing tests for distinct tenants, same-tenant pages, neighboring links/redirects, canonical URL, and legacy SQLite duplicate handling without rewriting old keys.
- [x] Implement scoped keys used by candidate preparation/batch additions; stored candidate URLs determine duplicates in existing runs.
- [x] Update usage guidance and diagnosis instructions, retaining scope limitations.
- [x] Run full suite, actual browser diagnostic and skill validation; save results.
- [x] Dispatch Astra/high review against task-owned changes; fix important findings with RED/GREEN tests; report any remaining limitations.

Commit steps intentionally omitted: no commit/push requested, and unrelated user changes are present.

Subsequent authorization (2026-11-05): the user requested commit/push, then resumption of the additional-company research. Commit only this plan's changes; retain unrelated dirty files and ignored research data.
