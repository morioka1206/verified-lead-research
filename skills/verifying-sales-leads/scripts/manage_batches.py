#!/usr/bin/env python3
"""Persist, resume, deduplicate, and export large lead-research runs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any

from finalize_run import CSV_COLUMNS, csv_row
from export_review_workbook import write_sales_workbook
from leadlib import canonicalize_url, company_key, finalize_record, utc_now, validate_campaign


DATABASE_NAME = "research.sqlite3"
CAMPAIGN_NAME = "campaign.json"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_array(path: Path, label: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{label} must be a JSON array of objects")
    return payload


def database_path(run_dir: Path) -> Path:
    return run_dir / DATABASE_NAME


def connect(run_dir: Path) -> sqlite3.Connection:
    path = database_path(run_dir)
    if not path.exists():
        raise ValueError(f"batch run is not initialized: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def load_campaign(run_dir: Path) -> dict[str, Any]:
    path = run_dir / CAMPAIGN_NAME
    if not path.exists():
        raise ValueError(f"campaign is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def initialize(campaign_path: Path, run_dir: Path) -> dict[str, Any]:
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    errors = validate_campaign(campaign)
    if errors:
        raise ValueError("; ".join(errors))
    if campaign.get("research_mode", "standard") != "batch":
        raise ValueError("manage_batches.py requires research_mode=batch")
    run_dir.mkdir(parents=True, exist_ok=True)
    saved_campaign = run_dir / CAMPAIGN_NAME
    if saved_campaign.exists():
        existing = json.loads(saved_campaign.read_text(encoding="utf-8"))
        if existing != campaign:
            raise ValueError("run directory already contains a different campaign")
    else:
        write_json(saved_campaign, campaign)
    connection = sqlite3.connect(database_path(run_dir))
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL CHECK(status IN ('open', 'completed')),
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS candidates (
            domain TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('queued', 'batched', 'completed')),
            batch_id INTEGER,
            batch_position INTEGER,
            added_at TEXT NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES batches(id)
        );
        CREATE TABLE IF NOT EXISTS records (
            domain TEXT PRIMARY KEY,
            batch_id INTEGER NOT NULL,
            batch_position INTEGER NOT NULL,
            record_json TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            FOREIGN KEY(domain) REFERENCES candidates(domain),
            FOREIGN KEY(batch_id) REFERENCES batches(id)
        );
        """
    )
    connection.commit()
    connection.close()
    return export_outputs(run_dir)


def add_candidates(run_dir: Path, input_path: Path, priority: int | None = None) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("candidate input must be a JSON array")
    connection = connect(run_dir)
    added = 0
    duplicates = 0
    invalid = []
    # Recompute semantic identity from saved URLs; never rewrite legacy PK/FK keys.
    seen_companies = {company_key(row['url']) for row in connection.execute('SELECT url FROM candidates')}
    for raw in payload:
        try:
            candidate = {"url": raw} if isinstance(raw, str) else dict(raw)
            candidate["url"] = canonicalize_url(candidate["url"])
            domain = company_key(candidate["url"])
            if priority is not None and "priority" not in candidate:
                candidate["priority"] = priority
            candidate_priority(candidate)
        except (KeyError, TypeError, ValueError) as exc:
            invalid.append({"candidate": raw, "reason": str(exc)})
            continue
        if domain in seen_companies:
            duplicates += 1
            continue
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO candidates
                (domain, url, payload_json, status, added_at)
            VALUES (?, ?, ?, 'queued', ?)
            """,
            (domain, candidate["url"], json.dumps(candidate, ensure_ascii=False), utc_now()),
        )
        if cursor.rowcount:
            added += 1
            seen_companies.add(domain)
        else:
            duplicates += 1
    connection.commit()
    discovered = connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    connection.close()
    result = {
        "status": "candidates_added",
        "added": added,
        "duplicates_skipped": duplicates,
        "invalid": invalid,
        "candidates_discovered": discovered,
    }
    return result


def candidate_priority(candidate: dict[str, Any]) -> int:
    """Higher numbers are batched first; missing means 0. Order never affects acceptance."""
    value = candidate.get("priority", 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"priority must be an integer: {value!r}")
    return value


def accepted_count(connection: sqlite3.Connection) -> int:
    return sum(
        json.loads(row["record_json"]).get("verification_status") == "accepted"
        for row in connection.execute("SELECT record_json FROM records")
    )


def checked_count(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]


def batch_file(run_dir: Path, batch_id: int) -> Path:
    return run_dir / "batches" / f"{batch_id:04d}" / "candidates.json"


def batch_candidates(connection: sqlite3.Connection, batch_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT payload_json FROM candidates WHERE batch_id = ? ORDER BY batch_position",
        (batch_id,),
    ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def next_batch(run_dir: Path) -> dict[str, Any]:
    campaign = load_campaign(run_dir)
    connection = connect(run_dir)
    open_batch = connection.execute(
        "SELECT id FROM batches WHERE status = 'open' ORDER BY id LIMIT 1"
    ).fetchone()
    if open_batch:
        batch_id = int(open_batch["id"])
        candidates = batch_candidates(connection, batch_id)
        path = batch_file(run_dir, batch_id)
        write_json(path, candidates)
        connection.close()
        return {
            "status": "resume_open_batch",
            "batch_id": batch_id,
            "candidate_count": len(candidates),
            "candidates_file": str(path),
        }

    accepted = accepted_count(connection)
    checked = checked_count(connection)
    target = int(campaign["target_accepted"])
    maximum = int(campaign["max_candidates"])
    if accepted >= target:
        connection.close()
        return {"status": "finished", "stop_reason": "target_met", "accepted": accepted, "checked": checked}
    if checked >= maximum:
        connection.close()
        return {
            "status": "finished",
            "stop_reason": "max_candidates_reached",
            "accepted": accepted,
            "checked": checked,
        }

    limit = min(int(campaign.get("batch_size", 50)), maximum - checked)
    # Highest priority first, then discovery order. Legacy payloads without a
    # priority count as 0, so existing runs keep their original order.
    rows = connection.execute(
        "SELECT domain, payload_json FROM candidates WHERE status = 'queued' ORDER BY rowid"
    ).fetchall()
    ranked = sorted(enumerate(rows), key=lambda item: (-int(json.loads(item[1]["payload_json"]).get("priority", 0) or 0), item[0]))
    queued = [row for _, row in ranked[:limit]]
    if not queued:
        connection.close()
        return {
            "status": "needs_candidates",
            "accepted": accepted,
            "checked": checked,
            "remaining_to_target": max(target - accepted, 0),
        }

    cursor = connection.execute(
        "INSERT INTO batches (status, created_at) VALUES ('open', ?)", (utc_now(),)
    )
    batch_id = int(cursor.lastrowid)
    for position, row in enumerate(queued, start=1):
        connection.execute(
            "UPDATE candidates SET status = 'batched', batch_id = ?, batch_position = ? WHERE domain = ?",
            (batch_id, position, row["domain"]),
        )
    connection.commit()
    candidates = batch_candidates(connection, batch_id)
    connection.close()
    path = batch_file(run_dir, batch_id)
    write_json(path, candidates)
    return {
        "status": "batch_created",
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "candidates_file": str(path),
    }


def load_human_labels(path: Path) -> dict[str, tuple[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row.get("公式URL", ""): (row.get("human_verdict", ""), row.get("human_notes", ""))
            for row in csv.DictReader(handle)
            if row.get("公式URL")
        }


def progress_summary(connection: sqlite3.Connection, campaign: dict[str, Any]) -> dict[str, Any]:
    status_counts = {status: 0 for status in ("accepted", "review", "rejected", "blocked")}
    for row in connection.execute("SELECT record_json FROM records"):
        status = json.loads(row["record_json"]).get("verification_status")
        if status in status_counts:
            status_counts[status] += 1
    accepted = status_counts["accepted"]
    checked = sum(status_counts.values())
    target = int(campaign["target_accepted"])
    maximum = int(campaign["max_candidates"])
    open_batches = connection.execute("SELECT COUNT(*) FROM batches WHERE status = 'open'").fetchone()[0]
    queued = connection.execute("SELECT COUNT(*) FROM candidates WHERE status = 'queued'").fetchone()[0]
    discovered = connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    completed_batches = connection.execute("SELECT COUNT(*) FROM batches WHERE status = 'completed'").fetchone()[0]
    if accepted >= target:
        stop_reason = "target_met"
        next_action = "finished"
    elif checked >= maximum:
        stop_reason = "max_candidates_reached"
        next_action = "finished"
    elif open_batches:
        stop_reason = None
        next_action = "complete_open_batch"
    elif queued:
        stop_reason = None
        next_action = "create_next_batch"
    else:
        stop_reason = None
        next_action = "discover_more_candidates"
    return {
        "generated_at": utc_now(),
        "research_mode": "batch",
        "batch_size": int(campaign.get("batch_size", 50)),
        "candidates_discovered": discovered,
        "candidates_queued": queued,
        "candidates_checked": checked,
        "accepted_available": accepted,
        "accepted_exported": min(accepted, target),
        "target_accepted": target,
        "remaining_to_target": max(target - accepted, 0),
        "target_met": accepted >= target,
        "max_candidates": maximum,
        "max_candidates_reached": checked >= maximum,
        "completed_batches": completed_batches,
        "open_batches": open_batches,
        "status_counts": status_counts,
        "stop_reason": stop_reason,
        "next_action": next_action,
    }


def export_outputs(run_dir: Path) -> dict[str, Any]:
    campaign = load_campaign(run_dir)
    connection = connect(run_dir)
    rows = connection.execute(
        "SELECT record_json FROM records ORDER BY batch_id, batch_position"
    ).fetchall()
    records = [json.loads(row["record_json"]) for row in rows]
    summary = progress_summary(connection, campaign)
    connection.close()
    write_json(run_dir / "audit.json", records)
    write_json(run_dir / "summary.json", summary)
    labels = load_human_labels(run_dir / "leads.csv")
    accepted = [record for record in records if record.get("verification_status") == "accepted"]
    accepted = accepted[: int(campaign["target_accepted"])]
    temporary = run_dir / "leads.csv.tmp"
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in accepted:
            row = csv_row(record)
            verdict, notes = labels.get(row["公式URL"], ("", ""))
            row["human_verdict"] = verdict
            row["human_notes"] = notes
            writer.writerow(row)
    temporary.replace(run_dir / "leads.csv")
    write_sales_workbook(accepted, run_dir / "leads.xlsx")
    return summary


def complete_batch(
    run_dir: Path,
    batch_id: int,
    crawls_path: Path,
    assessments_path: Path,
) -> dict[str, Any]:
    crawls = read_array(crawls_path, "crawls")
    assessments = read_array(assessments_path, "assessments")
    campaign = load_campaign(run_dir)
    connection = connect(run_dir)
    batch = connection.execute("SELECT status FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if not batch:
        connection.close()
        raise ValueError(f"unknown batch: {batch_id}")
    if batch["status"] != "open":
        connection.close()
        raise ValueError(f"batch {batch_id} is already completed")
    expected_rows = connection.execute(
        "SELECT domain, url, batch_position FROM candidates WHERE batch_id = ? ORDER BY batch_position",
        (batch_id,),
    ).fetchall()
    expected_urls = {row["url"] for row in expected_rows}
    crawl_by_url: dict[str, dict[str, Any]] = {}
    for crawl in crawls:
        url = (crawl.get("candidate") or {}).get("url")
        if not url or url in crawl_by_url:
            connection.close()
            raise ValueError("every crawl must have one unique candidate.url")
        crawl_by_url[url] = crawl
    assessment_by_url: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        url = assessment.get("candidate_url")
        if not url or url in assessment_by_url:
            connection.close()
            raise ValueError("every assessment must have one unique candidate_url")
        assessment_by_url[url] = assessment
    if set(crawl_by_url) != expected_urls:
        connection.close()
        raise ValueError("crawl URLs must exactly match the open batch")
    if set(assessment_by_url) != expected_urls:
        connection.close()
        raise ValueError("assessment URLs must exactly match the open batch")

    completed_at = utc_now()

    def identity(url: Any) -> str | None:
        try:
            return company_key(canonicalize_url(url)) if url else None
        except (TypeError, ValueError):
            return None

    accepted_identities = set()
    for (existing_json,) in connection.execute("SELECT record_json FROM records").fetchall():
        existing = json.loads(existing_json)
        if existing.get("verification_status") == "accepted":
            accepted_identities.add(identity(existing.get("canonical_url")))
    try:
        for row in expected_rows:
            crawl = crawl_by_url[row["url"]]
            assessment = assessment_by_url[row["url"]]
            record = finalize_record(crawl, assessment, campaign)
            # Distinct candidate domains can redirect to one company site; keep only the first acceptance.
            key = identity(record.get("canonical_url"))
            if record.get("verification_status") == "accepted" and key in accepted_identities:
                record["verification_status"] = "review"
                record["uncertainties"] = list(record.get("uncertainties") or []) + [
                    "Duplicate company: the same canonical site is already accepted in this run"
                ]
            elif record.get("verification_status") == "accepted":
                accepted_identities.add(key)
            connection.execute(
                """
                INSERT INTO records
                    (domain, batch_id, batch_position, record_json, completed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["domain"],
                    batch_id,
                    row["batch_position"],
                    json.dumps(record, ensure_ascii=False),
                    completed_at,
                ),
            )
            connection.execute(
                "UPDATE candidates SET status = 'completed' WHERE domain = ?",
                (row["domain"],),
            )
        connection.execute(
            "UPDATE batches SET status = 'completed', completed_at = ? WHERE id = ?",
            (completed_at, batch_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise
    connection.close()
    directory = run_dir / "batches" / f"{batch_id:04d}"
    write_json(directory / "crawls.json", crawls)
    write_json(directory / "assessments.json", assessments)
    return export_outputs(run_dir)


def downgrade_records(run_dir: Path, decisions_path: Path) -> dict[str, Any]:
    """Lower completed records to review (never upgrade). Decisions: [{canonical_url, decision, reason_ja, batch_id?}]; batch_id limits it to one batch."""
    decisions = read_array(decisions_path, "downgrade decisions")
    wanted = {}
    for item in decisions:
        if item.get("decision") != "downgrade":
            continue
        reason = str(item.get("reason_ja") or "").strip()
        if not reason:
            raise ValueError(f"downgrade needs reason_ja: {item.get('canonical_url')}")
        wanted[company_key(canonicalize_url(item["canonical_url"]))] = (reason, item.get("batch_id"))
    connection = connect(run_dir)
    changed, not_found = [], set(wanted)
    with connection:
        for row in connection.execute("SELECT rowid, batch_id, record_json FROM records").fetchall():
            record = json.loads(row["record_json"])
            url = record.get("canonical_url") or record.get("final_url")
            if not url:
                continue
            key = company_key(canonicalize_url(url))
            if key not in wanted:
                continue
            reason, only_batch = wanted[key]
            if only_batch is not None and int(only_batch) != int(row["batch_id"]):
                continue
            not_found.discard(key)
            if record.get("verification_status") != "accepted":
                continue
            record["verification_status"] = "review"
            record["uncertainties"] = list(record.get("uncertainties") or []) + ["監査で格下げ：" + reason]
            record["downgraded_at"] = utc_now()
            connection.execute("UPDATE records SET record_json = ? WHERE rowid = ?", (json.dumps(record, ensure_ascii=False), row["rowid"]))
            changed.append(url)
    connection.close()
    summary = export_outputs(run_dir)
    return {"status": "downgraded", "downgraded": changed, "not_found": sorted(not_found), "accepted_available": summary.get("accepted_available")}


def reassess_batch(run_dir: Path, batch_id: int, crawls_path: Path, assessments_path: Path) -> dict[str, Any]:
    """Re-judge records of a completed batch after the campaign definition changed.

    Only the companies present in the assessments file are re-finalized, through the
    same deterministic gate as complete-batch (evidence on page, every exclusion,
    blocked sites, duplicate canonical sites). The previous status is kept in
    `reassessment_history`. Use only after the user changed the campaign's
    acceptance definition (for example product_evidence), never to override a gate.
    """
    crawls = {(c.get("candidate") or {}).get("url"): c for c in read_array(crawls_path, "crawls")}
    assessments = read_array(assessments_path, "assessments")
    campaign = load_campaign(run_dir)
    errors = validate_campaign(campaign)
    if errors:
        raise ValueError("; ".join(errors))
    connection = connect(run_dir)
    batch = connection.execute("SELECT status FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if not batch or batch["status"] != "completed":
        connection.close()
        raise ValueError(f"batch {batch_id} is not a completed batch")
    rows = {
        row["url"]: row
        for row in connection.execute(
            "SELECT c.url, r.rowid AS rid, r.record_json FROM candidates c JOIN records r ON r.domain = c.domain "
            "WHERE c.batch_id = ? AND r.batch_id = ?",
            (batch_id, batch_id),
        ).fetchall()
    }

    def identity(url: Any) -> str | None:
        try:
            return company_key(canonicalize_url(url)) if url else None
        except (TypeError, ValueError):
            return None

    accepted_elsewhere = set()
    target_urls = {a.get("candidate_url") for a in assessments}
    for row in connection.execute("SELECT r.record_json, c.url FROM records r JOIN candidates c ON c.domain = r.domain").fetchall():
        existing = json.loads(row["record_json"])
        if existing.get("verification_status") == "accepted" and row["url"] not in target_urls:
            accepted_elsewhere.add(identity(existing.get("canonical_url")))
    changed: dict[str, int] = {}
    with connection:
        for assessment in assessments:
            url = assessment.get("candidate_url")
            if url not in rows or url not in crawls:
                raise ValueError(f"not a candidate of batch {batch_id} with a crawl: {url}")
            previous = json.loads(rows[url]["record_json"])
            record = finalize_record(crawls[url], assessment, campaign)
            key = identity(record.get("canonical_url"))
            if record.get("verification_status") == "accepted" and key in accepted_elsewhere:
                record["verification_status"] = "review"
                record["uncertainties"] = list(record.get("uncertainties") or []) + [
                    "Duplicate company: the same canonical site is already accepted in this run"
                ]
            elif record.get("verification_status") == "accepted":
                accepted_elsewhere.add(key)
            history = list(previous.get("reassessment_history") or [])
            history.append({"previous_status": previous.get("verification_status"), "reassessed_at": utc_now()})
            record["reassessment_history"] = history
            connection.execute("UPDATE records SET record_json = ? WHERE rowid = ?", (json.dumps(record, ensure_ascii=False), rows[url]["rid"]))
            transition = f"{previous.get('verification_status')}->{record['verification_status']}"
            changed[transition] = changed.get(transition, 0) + 1
    connection.close()
    summary = export_outputs(run_dir)
    return {"status": "reassessed", "batch_id": batch_id, "transitions": changed, "accepted_available": summary.get("accepted_available")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--campaign", required=True, type=Path)
    init_parser.add_argument("--run-dir", required=True, type=Path)

    add_parser = subparsers.add_parser("add-candidates")
    add_parser.add_argument("--run-dir", required=True, type=Path)
    add_parser.add_argument("--input", required=True, type=Path)
    add_parser.add_argument("--priority", type=int,
                            help="batching priority for these candidates (higher first; default 0); "
                                 "a candidate's own priority field wins")

    next_parser = subparsers.add_parser("next-batch")
    next_parser.add_argument("--run-dir", required=True, type=Path)

    complete_parser = subparsers.add_parser("complete-batch")
    complete_parser.add_argument("--run-dir", required=True, type=Path)
    complete_parser.add_argument("--batch-id", required=True, type=int)
    complete_parser.add_argument("--crawls", required=True, type=Path)
    complete_parser.add_argument("--assessments", required=True, type=Path)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--run-dir", required=True, type=Path)

    reassess_parser = subparsers.add_parser("reassess", help="re-judge part of a completed batch after the campaign definition changed")
    reassess_parser.add_argument("--run-dir", required=True, type=Path)
    reassess_parser.add_argument("--batch-id", required=True, type=int)
    reassess_parser.add_argument("--crawls", required=True, type=Path)
    reassess_parser.add_argument("--assessments", required=True, type=Path)

    downgrade_parser = subparsers.add_parser("downgrade", help="lower completed accepted records to review (never upgrades)")
    downgrade_parser.add_argument("--run-dir", required=True, type=Path)
    downgrade_parser.add_argument("--decisions", required=True, type=Path)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--run-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "init":
        result = initialize(args.campaign, args.run_dir)
    elif args.command == "add-candidates":
        result = add_candidates(args.run_dir, args.input, args.priority)
    elif args.command == "next-batch":
        result = next_batch(args.run_dir)
    elif args.command == "complete-batch":
        result = complete_batch(args.run_dir, args.batch_id, args.crawls, args.assessments)
    elif args.command == "reassess":
        result = reassess_batch(args.run_dir, args.batch_id, args.crawls, args.assessments)
    elif args.command == "downgrade":
        result = downgrade_records(args.run_dir, args.decisions)
    elif args.command == "status":
        result = export_outputs(args.run_dir)
    else:
        result = export_outputs(args.run_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
