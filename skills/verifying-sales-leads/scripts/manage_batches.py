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
from leadlib import canonicalize_url, domain_key, finalize_record, utc_now, validate_campaign


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


def add_candidates(run_dir: Path, input_path: Path) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("candidate input must be a JSON array")
    connection = connect(run_dir)
    added = 0
    duplicates = 0
    invalid = []
    for raw in payload:
        try:
            candidate = {"url": raw} if isinstance(raw, str) else dict(raw)
            candidate["url"] = canonicalize_url(candidate["url"])
            domain = domain_key(candidate["url"])
        except (KeyError, TypeError, ValueError) as exc:
            invalid.append({"candidate": raw, "reason": str(exc)})
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
    queued = connection.execute(
        "SELECT domain FROM candidates WHERE status = 'queued' ORDER BY rowid LIMIT ?",
        (limit,),
    ).fetchall()
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
    return summary


def complete_batch(
    run_dir: Path,
    batch_id: int,
    crawls_path: Path,
    assessments_path: Path,
) -> dict[str, Any]:
    crawls = read_array(crawls_path, "crawls")
    assessments = read_array(assessments_path, "assessments")
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
    try:
        for row in expected_rows:
            crawl = crawl_by_url[row["url"]]
            assessment = assessment_by_url[row["url"]]
            record = finalize_record(crawl, assessment)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--campaign", required=True, type=Path)
    init_parser.add_argument("--run-dir", required=True, type=Path)

    add_parser = subparsers.add_parser("add-candidates")
    add_parser.add_argument("--run-dir", required=True, type=Path)
    add_parser.add_argument("--input", required=True, type=Path)

    next_parser = subparsers.add_parser("next-batch")
    next_parser.add_argument("--run-dir", required=True, type=Path)

    complete_parser = subparsers.add_parser("complete-batch")
    complete_parser.add_argument("--run-dir", required=True, type=Path)
    complete_parser.add_argument("--batch-id", required=True, type=int)
    complete_parser.add_argument("--crawls", required=True, type=Path)
    complete_parser.add_argument("--assessments", required=True, type=Path)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--run-dir", required=True, type=Path)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--run-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "init":
        result = initialize(args.campaign, args.run_dir)
    elif args.command == "add-candidates":
        result = add_candidates(args.run_dir, args.input)
    elif args.command == "next-batch":
        result = next_batch(args.run_dir)
    elif args.command == "complete-batch":
        result = complete_batch(args.run_dir, args.batch_id, args.crawls, args.assessments)
    elif args.command == "status":
        result = export_outputs(args.run_dir)
    else:
        result = export_outputs(args.run_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
