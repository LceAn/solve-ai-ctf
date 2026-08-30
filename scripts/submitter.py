#!/usr/bin/env python3
"""Dedicated flag submitter with dry-run default, deduplication, rate limits, and response parsing.

Configured entirely through the competition's competition.json platform section. Secrets come
from environment variables, never from config files or command lines. All submissions append
to submissions.jsonl as the durable history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SUBMISSIONS_FILE = "submissions.jsonl"
RETRYABLE_DEFAULT = {429, 500, 502, 503}
MAX_FLAG_LENGTH = 1024


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def load_comp(comp_dir: Path) -> dict[str, Any]:
    path = comp_dir / "competition.json"
    if not path.exists():
        raise FileNotFoundError(f"competition file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def find_entry(data: dict[str, Any], challenge_ref: str) -> dict[str, Any]:
    for entry in data.get("challenges", []):
        if entry["slug"] == challenge_ref or entry.get("name") == challenge_ref:
            return entry
    raise KeyError(f"challenge not registered in competition.json: {challenge_ref}")


def read_case(comp_dir: Path, slug: str) -> dict[str, Any] | None:
    path = comp_dir / "cases" / slug / "case.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_submissions(comp_dir: Path) -> list[dict[str, Any]]:
    path = comp_dir / SUBMISSIONS_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def append_submission(comp_dir: Path, record: dict[str, Any]) -> None:
    with (comp_dir / SUBMISSIONS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_rate_limit(raw: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for pair in raw.split(","):
        key, _, value = pair.partition("=")
        if key.strip() and value.strip():
            values[key.strip()] = float(value.strip())
    return values


def rate_limit_status(records: list[dict[str, Any]], limits: dict[str, float], now: float) -> dict[str, Any]:
    live = [r for r in records if not r.get("dry_run", True)]
    min_interval = limits.get("min_interval_seconds", 0.0)
    window = limits.get("window_seconds", 300.0)
    max_per_window = limits.get("max_per_window", 20.0)
    last_time = max((r.get("epoch") or 0.0 for r in live), default=0.0)
    windowed = [r for r in live if (r.get("epoch") or 0.0) > now - window]
    status = {
        "live_total": len(live),
        "live_in_window": len(windowed),
        "min_interval_seconds": min_interval,
        "max_per_window": max_per_window,
        "window_seconds": window,
        "wait_seconds": max(0.0, min_interval - (now - last_time)) if last_time else 0.0,
        "window_exhausted": len(windowed) >= max_per_window,
    }
    return status


def resolve_token(platform: dict[str, Any]) -> str:
    auth = platform.get("auth", {})
    env_name = auth.get("value_env") or "CTF_TOKEN"
    token = os.environ.get(env_name, "")
    if not token and auth.get("value"):
        token = str(auth["value"])
    return token


def build_request(data: dict[str, Any], entry: dict[str, Any], flag: str, token: str) -> dict[str, Any]:
    platform = data.get("platform", {})
    submit = platform.get("submit", {})
    base = platform.get("base_url", "").rstrip("/")
    path = submit.get("path", "")
    if not base and not path.startswith("http"):
        raise ValueError("platform.base_url is not configured")
    url = path if path.startswith("http") else f"{base}{path}"
    competition_id = data.get("competition_id", "")
    challenge_id = entry.get("platform_id", "")
    if not challenge_id:
        raise ValueError(f"challenge {entry['slug']} has no platform_id")
    method = submit.get("method", "POST").upper()
    content_type = submit.get("content_type", "application/x-www-form-urlencoded")
    template = submit.get("body_template", "")
    if not template:
        template = submit.get("json_body_template", "")
    substitutions = {
        "competition_id": competition_id, "challenge_id": challenge_id, "flag": flag,
        "ctfThemeId": challenge_id, "userAnswer": flag,
    }
    body = template
    for placeholder, value in substitutions.items():
        body = body.replace("{" + placeholder + "}", value)
    if not body and content_type == "application/json" and flag:
        body = json.dumps({"flag": flag, "challengeId": challenge_id})
    headers = {"Content-Type": content_type}
    if submit.get("idempotency_header"):
        headers[submit["idempotency_header"]] = hashlib.sha256(
            f"{entry['slug']}:{flag}".encode()
        ).hexdigest()
    auth = platform.get("auth", {})
    if token:
        headers[auth.get("header", "Authorization")] = f"{auth.get('value_prefix', '')}{token}".strip()
    return {"url": url, "method": method, "body": body, "headers": headers}


def mask_headers(headers: dict[str, str]) -> dict[str, str]:
    masked = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in {"authorization", "cookie", "x-api-key"}:
            masked[key] = value[:8] + "..." if len(value) > 8 else "..."
        else:
            masked[key] = value
    return masked


def send(request: dict[str, Any], timeout: float) -> tuple[int, str, str]:
    data = request["body"].encode("utf-8")
    req = urllib.request.Request(request["url"], data=data, method=request["method"])
    for key, value in request["headers"].items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace"), ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace"), str(exc)
    except urllib.error.URLError as exc:
        return 0, "", str(exc)


def parse_response(platform: dict[str, Any], http_status: int, body: str) -> dict[str, Any]:
    submit = platform.get("submit", {})
    parsed: Any = None
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    outcome = "unknown"
    reason = ""
    if http_status == 0:
        outcome, reason = "error", "network failure"
    elif http_status in submit.get("retryable_http_codes", list(RETRYABLE_DEFAULT)):
        outcome, reason = "retryable", f"HTTP {http_status}"
    elif parsed is not None:
        success = submit.get("success", {})
        field = success.get("field", "data")
        expected = success.get("equals", True)
        value = parsed.get(field) if isinstance(parsed, dict) else None
        if field in (parsed if isinstance(parsed, dict) else {}) and value == expected:
            outcome, reason = "accepted", f"{field}={value!r}"
        else:
            outcome, reason = "rejected", f"HTTP {http_status} parsed response"
    elif http_status == 200:
        outcome, reason = "unknown", "HTTP 200 but response not parsed"
    else:
        outcome, reason = "rejected", f"HTTP {http_status}"
    return {"http_status": http_status, "outcome": outcome, "reason": reason, "body_excerpt": body[:300]}


def cmd_submit(args: argparse.Namespace) -> int:
    if len(args.flag) > MAX_FLAG_LENGTH:
        print("flag exceeds maximum length", file=sys.stderr)
        return 2
    data = load_comp(args.comp_dir)
    entry = find_entry(data, args.challenge)
    case = read_case(args.comp_dir, entry["slug"])
    if case is None:
        print(f"no case.json for {entry['slug']}; register the challenge first", file=sys.stderr)
        return 2
    if args.candidate:
        candidate = next(
            (item for item in case.get("candidates", []) if item["id"] == args.candidate), None
        )
        if candidate is None:
            print(f"unknown candidate {args.candidate} in {entry['slug']}", file=sys.stderr)
            return 2
        if candidate["status"] not in {"validated", "submitted"} and not args.allow_unvalidated:
            print(
                f"candidate {args.candidate} is {candidate['status']}; validate it first or use --allow-unvalidated",
                file=sys.stderr,
            )
            return 2
        if candidate["value"] != args.flag:
            print("--flag does not match the stored candidate value", file=sys.stderr)
            return 2

    flag_hash = hashlib.sha256(args.flag.encode()).hexdigest()
    records = read_submissions(args.comp_dir)
    for record in records:
        if record.get("dry_run", True):
            continue
        if record.get("challenge_slug") == entry["slug"] and record.get("flag_sha256") == flag_hash:
            print(
                f"duplicate: this flag was already submitted at {record.get('time')} (outcome={record.get('outcome')})",
                file=sys.stderr,
            )
            return 2

    limits = parse_rate_limit(data.get("rate_limit", ""))
    now = timestamp_now()
    rate = rate_limit_status(records, limits, now)
    if rate["window_exhausted"]:
        print(
            f"rate limit: {rate['live_in_window']} live submissions in the last {rate['window_seconds']:.0f}s (max {rate['max_per_window']:.0f})",
            file=sys.stderr,
        )
        return 2
    if rate["wait_seconds"] > 0:
        print(f"rate limit: wait {rate['wait_seconds']:.1f}s since the last live submission", file=sys.stderr)
        return 2

    token = resolve_token(data.get("platform", {}))
    request = build_request(data, entry, args.flag, token)

    record = {
        "time": utcnow(),
        "epoch": now,
        "challenge_slug": entry["slug"],
        "challenge_id": entry.get("platform_id", ""),
        "flag_sha256": flag_hash,
        "source": args.source or "manual",
        "note": args.note or "",
        "dry_run": not args.live,
        "request": {
            "url": request["url"],
            "method": request["method"],
            "body": request["body"].replace(args.flag, "<flag>"),
            "headers": mask_headers(request["headers"]),
        },
        "outcome": "dry_run",
        "response": {},
    }

    if not args.live:
        append_submission(args.comp_dir, record)
        print(json.dumps({
            "mode": "dry-run (no request sent)",
            "challenge": entry["slug"],
            "flag_sha256": flag_hash,
            "request": record["request"],
            "rate_limit": rate,
        }, ensure_ascii=False, indent=2))
        print("use --live to send the real request")
        return 0

    platform = data.get("platform", {})
    timeout = float(platform.get("submit", {}).get("timeout_seconds", 15))
    http_status, body, error = send(request, timeout)
    response = parse_response(platform, http_status, body)
    record["response"] = response
    record["outcome"] = response["outcome"]
    append_submission(args.comp_dir, record)

    if args.update_case and args.candidate:
        case_dir = args.comp_dir / "cases" / entry["slug"]
        new_status = "accepted" if response["outcome"] == "accepted" else "submitted"
        subprocess.run(
            [sys.executable, str(HERE / "case_manager.py"), "candidate", str(case_dir), args.candidate, new_status],
            check=False,
        )

    print(json.dumps({
        "challenge": entry["slug"],
        "outcome": response["outcome"],
        "reason": response["reason"],
        "http_status": response["http_status"],
    }, ensure_ascii=False, indent=2))
    return 0 if response["outcome"] == "accepted" else 1


def cmd_history(args: argparse.Namespace) -> int:
    records = read_submissions(args.comp_dir)
    for record in records[-args.last:]:
        print(
            f"{record['time']}  {record.get('challenge_slug', '?'):<24} "
            f"{record.get('outcome', '?'):<12} {'DRY' if record.get('dry_run') else 'LIVE'}"
        )
    return 0


def cmd_rate(args: argparse.Namespace) -> int:
    data = load_comp(args.comp_dir)
    limits = parse_rate_limit(data.get("rate_limit", ""))
    status = rate_limit_status(read_submissions(args.comp_dir), limits, timestamp_now())
    print(json.dumps(status, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("comp_dir", type=Path)
    submit.add_argument("--challenge", required=True)
    submit.add_argument("--flag", required=True)
    submit.add_argument("--candidate")
    submit.add_argument("--allow-unvalidated", action="store_true")
    submit.add_argument("--source", default="manual")
    submit.add_argument("--note", default="")
    submit.add_argument("--live", action="store_true")
    submit.add_argument("--update-case", action="store_true")
    submit.set_defaults(func=cmd_submit)

    history = sub.add_parser("history")
    history.add_argument("comp_dir", type=Path)
    history.add_argument("--last", type=int, default=20)
    history.set_defaults(func=cmd_history)

    rate = sub.add_parser("rate")
    rate.add_argument("comp_dir", type=Path)
    rate.set_defaults(func=cmd_rate)

    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"submitter error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
