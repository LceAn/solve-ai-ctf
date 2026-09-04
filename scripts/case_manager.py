#!/usr/bin/env python3
"""Create and maintain an auditable per-challenge CTF case record."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
CASE_FILE = "case.json"
STATUSES = {"new", "triaged", "in_progress", "blocked", "candidate_found", "solved", "submitted", "closed", "abandoned", "invalid"}
HYPOTHESIS_STATUSES = {"proposed", "running", "supported", "rejected", "parked"}
OUTCOMES = {"success", "failure", "partial", "error"}
CANDIDATE_STATUSES = {"unverified", "validated", "rejected", "submitted", "accepted"}
FLAG_RE = re.compile(rb"(?i)(?:flag|hkcert|ctf)\{[^}\r\n]{1,256}\}")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def configure_stdio() -> None:
    """Keep CLI output usable when a platform string is outside the console code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def case_path(case_dir: Path) -> Path:
    return case_dir / CASE_FILE


def load_case(case_dir: Path) -> dict[str, Any]:
    path = case_path(case_dir)
    if not path.exists():
        raise FileNotFoundError(f"case file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def next_id(items: Iterable[dict[str, Any]], prefix: str) -> str:
    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for item in items:
        match = pattern.match(str(item.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:04d}"


def event(case: dict[str, Any], kind: str, detail: dict[str, Any]) -> None:
    case.setdefault("events", []).append({
        "id": next_id(case.get("events", []), "EV"),
        "time": utcnow(),
        "kind": kind,
        "detail": detail,
    })
    case["updated_at"] = utcnow()


def cmd_init(args: argparse.Namespace) -> int:
    path = case_path(args.case_dir)
    if path.exists() and not args.force:
        print(f"refusing to overwrite existing {path}; use --force", file=sys.stderr)
        return 2
    args.case_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "challenge": {
            "id": args.challenge_id,
            "name": args.name,
            "category": args.category,
            "difficulty": args.difficulty,
            "points": args.points,
            "description": args.description,
            "flag_patterns": args.flag_pattern or ["(?i)(?:flag|hkcert|ctf)\\{[^}]+\\}"],
        },
        "authorization": {"scope": args.scope, "confirmed": bool(args.scope)},
        "status": "new",
        "blocked_on": None,
        "unblock_when": [],
        "artifacts": [],
        "evidence": [],
        "hypotheses": [],
        "attempts": [],
        "candidates": [],
        "next_actions": [],
        "events": [],
    }
    event(data, "case_initialized", {"name": args.name, "category": args.category})
    atomic_write(path, data)
    print(path)
    return 0


def cmd_finding(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    if not 0.0 <= args.confidence <= 1.0:
        print("confidence must be between 0 and 1", file=sys.stderr)
        return 2
    finding = {
        "id": next_id(case["evidence"], "E"),
        "time": utcnow(),
        "claim": args.claim,
        "source": args.source,
        "artifact": args.artifact,
        "confidence": args.confidence,
        "kind": args.kind,
        "phase": args.phase,
    }
    case["evidence"].append(finding)
    event(case, "evidence_added", {"evidence_id": finding["id"]})
    atomic_write(case_path(args.case_dir), case)
    print(finding["id"])
    return 0


def cmd_hypothesis(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    evidence_ids = args.evidence or []
    known = {item["id"] for item in case["evidence"]}
    missing = sorted(set(evidence_ids) - known)
    if missing:
        print(f"unknown evidence IDs: {', '.join(missing)}", file=sys.stderr)
        return 2
    item = {
        "id": next_id(case["hypotheses"], "H"),
        "created_at": utcnow(),
        "title": args.title,
        "rationale": args.rationale,
        "expected_signal": args.expected,
        "stop_condition": args.stop,
        "estimated_minutes": args.minutes,
        "priority": args.priority,
        "status": "proposed",
        "evidence_ids": evidence_ids,
    }
    case["hypotheses"].append(item)
    event(case, "hypothesis_added", {"hypothesis_id": item["id"]})
    atomic_write(case_path(args.case_dir), case)
    print(item["id"])
    return 0


def cmd_attempt(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    hypothesis = next((item for item in case["hypotheses"] if item["id"] == args.hypothesis), None)
    if hypothesis is None:
        print(f"unknown hypothesis: {args.hypothesis}", file=sys.stderr)
        return 2
    known_evidence = {item["id"] for item in case["evidence"]}
    missing = sorted(set(args.evidence or []) - known_evidence)
    if missing:
        print(f"unknown evidence IDs: {', '.join(missing)}", file=sys.stderr)
        return 2
    item = {
        "id": next_id(case["attempts"], "A"),
        "time": utcnow(),
        "hypothesis_id": args.hypothesis,
        "action": args.action,
        "result": args.result,
        "outcome": args.outcome,
        "evidence_ids": args.evidence or [],
        "artifact": args.artifact,
        "duration_seconds": args.duration,
    }
    case["attempts"].append(item)
    hypothesis["status"] = args.hypothesis_status or {
        "success": "supported", "failure": "rejected", "partial": "running", "error": "parked"
    }[args.outcome]
    if case["status"] in {"new", "triaged"}:
        case["status"] = "in_progress"
    event(case, "attempt_added", {"attempt_id": item["id"], "hypothesis_id": args.hypothesis, "outcome": args.outcome})
    atomic_write(case_path(args.case_dir), case)
    print(item["id"])
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    old = case["status"]
    case["status"] = args.status
    case["blocked_on"] = args.blocked_on if args.status == "blocked" else None
    case["unblock_when"] = args.unblock_when or [] if args.status == "blocked" else []
    event(case, "status_changed", {"old": old, "new": args.status, "reason": args.reason})
    atomic_write(case_path(args.case_dir), case)
    print(f"{old} -> {args.status}")
    return 0


def candidate_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    ignored = {"case.json", "writeup.md", "writeup-draft.md", "summary.md"}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.name.lower() not in ignored:
            yield path


def scan_file(path: Path, max_bytes: int) -> set[str]:
    found: set[str] = set()
    try:
        with path.open("rb") as handle:
            remaining = max_bytes
            carry = b""
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                data = carry + chunk
                for match in FLAG_RE.findall(data):
                    found.add(match.decode("utf-8", errors="replace"))
                carry = data[-512:]
                remaining -= len(chunk)
    except (OSError, PermissionError):
        pass
    return found


def cmd_scan_flags(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    root = args.search_root.resolve()
    results: list[tuple[str, str]] = []
    for path in candidate_files(root):
        for value in sorted(scan_file(path, args.max_bytes)):
            results.append((value, str(path)))
    existing = {(item["value"], item["source"]) for item in case["candidates"]}
    for value, source in results:
        print(f"{value}\t{source}")
        if args.store and (value, source) not in existing:
            candidate = {
                "id": next_id(case["candidates"], "C"),
                "time": utcnow(),
                "value": value,
                "source": source,
                "status": "unverified",
                "validation": [],
            }
            case["candidates"].append(candidate)
            existing.add((value, source))
    if args.store and results:
        if case["status"] not in {"solved", "submitted", "closed"}:
            case["status"] = "candidate_found"
        event(case, "flag_scan", {"root": str(root), "candidate_count": len(results)})
        atomic_write(case_path(args.case_dir), case)
    return 0 if results else 1


def cmd_candidate(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    candidate = next((item for item in case["candidates"] if item["id"] == args.candidate_id), None)
    if candidate is None:
        print(f"unknown candidate: {args.candidate_id}", file=sys.stderr)
        return 2
    old = candidate["status"]
    candidate["status"] = args.status
    if args.note:
        candidate.setdefault("validation", []).append({"time": utcnow(), "status": args.status, "note": args.note})
    if args.status == "validated" and case["status"] == "candidate_found":
        case["status"] = "solved"
    elif args.status == "submitted":
        case["status"] = "submitted"
    elif args.status == "accepted":
        case["status"] = "submitted"
    event(case, "candidate_status_changed", {"candidate_id": args.candidate_id, "old": old, "new": args.status})
    atomic_write(case_path(args.case_dir), case)
    print(f"{args.candidate_id}: {old} -> {args.status}")
    return 0


def validate(case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if case.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {case.get('schema_version')}")
    if case.get("status") not in STATUSES:
        errors.append(f"invalid status: {case.get('status')}")
    if not case.get("challenge", {}).get("name"):
        errors.append("challenge.name is required")
    if case.get("status") == "blocked" and not case.get("blocked_on"):
        errors.append("blocked status requires blocked_on")
    collections = {
        "evidence": case.get("evidence", []), "hypotheses": case.get("hypotheses", []),
        "attempts": case.get("attempts", []), "candidates": case.get("candidates", []),
        "events": case.get("events", []),
    }
    all_ids: set[str] = set()
    for name, items in collections.items():
        for item in items:
            item_id = item.get("id")
            if not item_id:
                errors.append(f"{name} item missing id")
            elif item_id in all_ids:
                errors.append(f"duplicate id: {item_id}")
            all_ids.add(item_id)
    evidence_ids = {item["id"] for item in collections["evidence"] if item.get("id")}
    hypothesis_ids = {item["id"] for item in collections["hypotheses"] if item.get("id")}
    for item in collections["hypotheses"]:
        if item.get("status") not in HYPOTHESIS_STATUSES:
            errors.append(f"{item.get('id')}: invalid hypothesis status")
        for evidence_id in item.get("evidence_ids", []):
            if evidence_id not in evidence_ids:
                errors.append(f"{item.get('id')}: unknown evidence {evidence_id}")
    for item in collections["attempts"]:
        if item.get("outcome") not in OUTCOMES:
            errors.append(f"{item.get('id')}: invalid outcome")
        if item.get("hypothesis_id") not in hypothesis_ids:
            errors.append(f"{item.get('id')}: unknown hypothesis {item.get('hypothesis_id')}")
        for evidence_id in item.get("evidence_ids", []):
            if evidence_id not in evidence_ids:
                errors.append(f"{item.get('id')}: unknown evidence {evidence_id}")
    for item in collections["candidates"]:
        if item.get("status") not in CANDIDATE_STATUSES:
            errors.append(f"{item.get('id')}: invalid candidate status")
    if case.get("status") in {"solved", "submitted", "closed"} and not any(
        item.get("status") in {"validated", "submitted", "accepted"} for item in collections["candidates"]
    ):
        errors.append("solved/submitted/closed status requires a validated candidate")
    return errors


def cmd_validate(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    errors = validate(case)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    case = load_case(args.case_dir)
    challenge = case["challenge"]
    lines = [
        f"# {challenge['name']} — Case Summary", "",
        f"- Status: **{case['status']}**",
        f"- Category: {challenge.get('category', 'auto')}",
        f"- Evidence: {len(case['evidence'])}",
        f"- Hypotheses: {len(case['hypotheses'])}",
        f"- Attempts: {len(case['attempts'])}",
        f"- Flag candidates: {len(case['candidates'])}", "",
    ]
    if case.get("blocked_on"):
        lines += ["## Blocker", "", case["blocked_on"], ""]
    lines += ["## Hypotheses", ""]
    for item in sorted(case["hypotheses"], key=lambda value: (-value.get("priority", 0), value["id"])):
        lines.append(f"- `{item['id']}` [{item['status']}] {item['title']}")
    lines += ["", "## Recent evidence", ""]
    for item in case["evidence"][-10:]:
        lines.append(f"- `{item['id']}` ({item['confidence']:.1f}) {item['claim']}")
    lines += ["", "## Recent attempts", ""]
    for item in case["attempts"][-10:]:
        lines.append(f"- `{item['id']}` `{item['hypothesis_id']}` {item['outcome']}: {item['action']}")
    output = "\n".join(lines)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("case_dir", type=Path)
    init.add_argument("--name", required=True)
    init.add_argument("--challenge-id")
    init.add_argument("--category", default="auto")
    init.add_argument("--difficulty")
    init.add_argument("--points", type=float)
    init.add_argument("--description", default="")
    init.add_argument("--scope", default="")
    init.add_argument("--flag-pattern", action="append")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    finding = sub.add_parser("finding")
    finding.add_argument("case_dir", type=Path)
    finding.add_argument("--claim", required=True)
    finding.add_argument("--source", required=True)
    finding.add_argument("--artifact")
    finding.add_argument("--confidence", type=float, default=0.5)
    finding.add_argument("--kind", choices=["observation", "inference", "confirmation", "warning"], default="observation")
    finding.add_argument("--phase", choices=["pre_match", "during_competition", "post_competition", "current"], default="current")
    finding.set_defaults(func=cmd_finding)

    hypothesis = sub.add_parser("hypothesis")
    hypothesis.add_argument("case_dir", type=Path)
    hypothesis.add_argument("--title", required=True)
    hypothesis.add_argument("--rationale", required=True)
    hypothesis.add_argument("--expected", required=True)
    hypothesis.add_argument("--stop", default="Two controlled failures without new evidence")
    hypothesis.add_argument("--minutes", type=float, default=15)
    hypothesis.add_argument("--priority", type=float, default=1.0)
    hypothesis.add_argument("--evidence", action="append")
    hypothesis.set_defaults(func=cmd_hypothesis)

    attempt = sub.add_parser("attempt")
    attempt.add_argument("case_dir", type=Path)
    attempt.add_argument("--hypothesis", required=True)
    attempt.add_argument("--action", required=True)
    attempt.add_argument("--result", required=True)
    attempt.add_argument("--outcome", choices=sorted(OUTCOMES), required=True)
    attempt.add_argument("--evidence", action="append")
    attempt.add_argument("--artifact")
    attempt.add_argument("--duration", type=float)
    attempt.add_argument("--hypothesis-status", choices=sorted(HYPOTHESIS_STATUSES))
    attempt.set_defaults(func=cmd_attempt)

    status = sub.add_parser("status")
    status.add_argument("case_dir", type=Path)
    status.add_argument("status", choices=sorted(STATUSES))
    status.add_argument("--reason", default="")
    status.add_argument("--blocked-on")
    status.add_argument("--unblock-when", action="append")
    status.set_defaults(func=cmd_status)

    scan = sub.add_parser("scan-flags")
    scan.add_argument("case_dir", type=Path)
    scan.add_argument("search_root", type=Path)
    scan.add_argument("--store", action="store_true")
    scan.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    scan.set_defaults(func=cmd_scan_flags)

    candidate = sub.add_parser("candidate")
    candidate.add_argument("case_dir", type=Path)
    candidate.add_argument("candidate_id")
    candidate.add_argument("status", choices=sorted(CANDIDATE_STATUSES))
    candidate.add_argument("--note", default="")
    candidate.set_defaults(func=cmd_candidate)

    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("case_dir", type=Path)
    validate_cmd.set_defaults(func=cmd_validate)

    summary = sub.add_parser("summary")
    summary.add_argument("case_dir", type=Path)
    summary.add_argument("--output", type=Path)
    summary.set_defaults(func=cmd_summary)
    return root


def main() -> int:
    configure_stdio()
    args = parser().parse_args()
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"case manager error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
