#!/usr/bin/env python3
"""Offline self-test for the bundled deterministic CTF utilities."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(*args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode != expected:
        raise AssertionError(
            f"command failed ({result.returncode}, expected {expected}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


class FlagHandler(BaseHTTPRequestHandler):
    requests = []
    session_cookies = []

    def do_GET(self):
        if self.path == "/login":
            payload = b'<form><input name="nonce" value="fixture-nonce"></form>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        elif self.path == "/challenges":
            payload = b"logged-in"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        else:
            payload = b"not-found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        if self.path == "/login":
            fields = urllib.parse.parse_qs(body)
            if (fields.get("name") == ["fixture-user"]
                    and fields.get("password") == ["fixture-pass"]
                    and fields.get("nonce") == ["fixture-nonce"]):
                self.send_response(302)
                self.send_header("Location", "/challenges")
                self.send_header("Set-Cookie", "session=fixture-session; Path=/")
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()
            return
        self.__class__.requests.append((self.path, body))
        if self.path.startswith("/api/v1/challenges/"):
            cookie = self.headers.get("Cookie", "")
            self.__class__.session_cookies.append(cookie)
            if "session=fixture-session" in cookie:
                payload = json.dumps({"data": {"status": "correct"}}).encode()
                self.send_response(200)
            else:
                payload = json.dumps({"success": False}).encode()
                self.send_response(401)
        else:
            payload = json.dumps({"code": "000000", "data": True}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def start_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FlagHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def platform_config(port: int, root: Path) -> Path:
    path = root / "platform.json"
    path.write_text(json.dumps({
        "base_url": f"http://127.0.0.1:{port}",
        "submit": {
            "method": "POST",
            "path": "/competition/person/ctf/commitAnswer",
            "content_type": "application/x-www-form-urlencoded",
            "body_template": "competitionId={competition_id}&ctfThemeId={challenge_id}&userAnswer={flag}",
            "success": {"field": "data", "equals": True},
            "retryable_http_codes": [429, 500, 502, 503],
            "timeout_seconds": 10,
        },
    }), encoding="utf-8")
    return path


def session_platform_config(port: int, root: Path) -> Path:
    path = root / "platform-session.json"
    path.write_text(json.dumps({
        "base_url": f"http://127.0.0.1:{port}",
        "login": {
            "method": "POST",
            "path": "/login",
            "content_type": "application/x-www-form-urlencoded",
            "fields": {"name": "{username}", "password": "{password}"},
            "csrf": {
                "field": "nonce", "from_path": "/login",
                "pattern": 'name="nonce"[^>]*value="([^"]+)"',
            },
            "credentials_env": "CTF_SESSION_TEST_CREDS",
            "success_redirect": "/challenges",
        },
        "submit": {
            "method": "POST",
            "path": "/api/v1/challenges/{challenge_id}/attempt",
            "content_type": "application/json",
            "body_template": '{"challenge_id": "{challenge_id}", "submission": "{flag}"}',
            "success": {"field": "data.status", "equals": "correct"},
            "timeout_seconds": 10,
        },
    }), encoding="utf-8")
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solve-ai-ctf-test-") as temp_name:
        root = Path(temp_name)
        artifacts = root / "artifacts"
        artifacts.mkdir()
        (artifacts / "challenge.py").write_text(
            "from Crypto.Util.number import getPrime\n"
            "# RSA AES getrandbits HTTP Flask\n"
            "print('flag{synthetic-test-only}')\n",
            encoding="utf-8",
        )
        (artifacts / "service").write_bytes(b"\x7fELF" + b"safe-linking tcache seccomp" * 20)

        triage_json = root / "triage.json"
        run(str(HERE / "triage.py"), str(artifacts), "--json-out", str(triage_json))
        report = json.loads(triage_json.read_text(encoding="utf-8"))
        assert report["file_count"] == 2
        assert report["classification"]["primary"] in {"pwn", "crypto", "web"}
        assert any(item.get("flag_like_count") == 1 for item in report["files"])

        case_dir = root / "case"
        run(
            str(HERE / "case_manager.py"), "init", str(case_dir),
            "--name", "Synthetic", "--category", "auto", "--scope", "Local authorized fixture",
        )
        evidence = run(
            str(HERE / "case_manager.py"), "finding", str(case_dir),
            "--claim", "ELF magic is present", "--source", str(triage_json), "--confidence", "0.8",
        ).stdout.strip()
        run(
            str(HERE / "case_manager.py"), "finding", str(case_dir),
            "--claim", "CTF² browser receipt is accepted", "--source", "synthetic-ui",
            "--confidence", "1.0", "--kind", "confirmation",
        )
        hypothesis = run(
            str(HERE / "case_manager.py"), "hypothesis", str(case_dir),
            "--title", "Direct executable path", "--rationale", "ELF evidence",
            "--expected", "Static inspection identifies the control path", "--evidence", evidence,
        ).stdout.strip()
        run(
            str(HERE / "case_manager.py"), "attempt", str(case_dir),
            "--hypothesis", hypothesis, "--action", "Static fixture inspection",
            "--result", "Synthetic success", "--outcome", "success", "--evidence", evidence,
        )
        run(
            str(HERE / "case_manager.py"), "scan-flags", str(case_dir), str(artifacts), "--store"
        )
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        candidate_id = case["candidates"][0]["id"]
        run(
            str(HERE / "case_manager.py"), "candidate", str(case_dir), candidate_id, "validated",
            "--note", "Synthetic fixture reproduced locally",
        )
        run(str(HERE / "case_manager.py"), "validate", str(case_dir))
        summary_path = case_dir / "summary.md"
        run(
            str(HERE / "case_manager.py"), "summary", str(case_dir),
            "--output", str(summary_path),
        )
        assert "CTF² browser receipt is accepted" in summary_path.read_text(encoding="utf-8")

        search = run(str(HERE / "kb_search.py"), "safe-linking tcache", "--category", "pwn", "--top", "3")
        assert "playbooks-pwn.md" in search.stdout or "case-corpus.md" in search.stdout

        server, thread = start_server()
        try:
            comp_dir = root / "comp"
            comp_dir.mkdir()
            run(
                str(HERE / "competition.py"), "init", str(comp_dir),
                "--name", "Synthetic CTF", "--scope", "Local authorized fixture",
                "--competition-id", "CID1",
                "--platform-config", str(platform_config(server.server_port, root)),
                "--rate-limit", "min_interval_seconds=0,max_per_window=20,window_seconds=300",
            )
            run(
                str(HERE / "competition.py"), "add-challenge", str(comp_dir),
                "--name", "Synthetic", "--category", "web", "--points", "100",
                "--challenge-id", "THEME1", "--difficulty", "Easy",
                "--description", "Synthetic fixture",
            )
            run(str(HERE / "competition.py"), "list", str(comp_dir))
            run(str(HERE / "competition.py"), "prioritize", str(comp_dir))
            dash = run(str(HERE / "competition.py"), "dashboard", str(comp_dir)).stdout.strip()
            assert Path(dash).exists()

            reg_case = comp_dir / "cases" / "cTHEME1"
            run(
                str(HERE / "case_manager.py"), "scan-flags", str(reg_case), str(artifacts), "--store"
            )
            reg = json.loads((reg_case / "case.json").read_text(encoding="utf-8"))
            reg_candidate = reg["candidates"][0]["id"]
            run(
                str(HERE / "case_manager.py"), "candidate", str(reg_case), reg_candidate, "validated",
                "--note", "Synthetic fixture reproduced locally",
            )

            dry = run(
                str(HERE / "submitter.py"), "submit", str(comp_dir),
                "--challenge", "cTHEME1", "--flag", "flag{synthetic-test-only}",
                "--candidate", reg_candidate,
            )
            assert "dry-run" in dry.stdout

            live = run(
                str(HERE / "submitter.py"), "submit", str(comp_dir),
                "--challenge", "cTHEME1", "--flag", "flag{synthetic-test-only}",
                "--candidate", reg_candidate, "--live", "--update-case",
            )
            assert '"outcome": "accepted"' in live.stdout
            assert len(FlagHandler.requests) == 1
            assert "competitionId=CID1" in FlagHandler.requests[0][1]
            assert "ctfThemeId=THEME1" in FlagHandler.requests[0][1]

            run(
                str(HERE / "submitter.py"), "submit", str(comp_dir),
                "--challenge", "cTHEME1", "--flag", "flag{synthetic-test-only}",
                expected=2,
            )

            run(str(HERE / "submitter.py"), "history", str(comp_dir))
            run(str(HERE / "submitter.py"), "rate", str(comp_dir))
            updated = json.loads((reg_case / "case.json").read_text(encoding="utf-8"))
            assert any(item["status"] == "accepted" for item in updated["candidates"])

            browser_only_cfg = json.loads((comp_dir / "competition.json").read_text(encoding="utf-8"))
            browser_only_cfg["platform"]["submission_mode"] = "browser_ui"
            (comp_dir / "competition.json").write_text(
                json.dumps(browser_only_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            browser_blocked = run(
                str(HERE / "submitter.py"), "submit", str(comp_dir),
                "--challenge", "cTHEME1", "--flag", "flag{browser-ui-live-block}", "--live",
                expected=2,
            )
            assert "browser-ui-only" in browser_blocked.stderr
            browser_only_cfg["platform"].pop("submission_mode", None)
            (comp_dir / "competition.json").write_text(
                json.dumps(browser_only_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            run(
                str(HERE / "competition.py"), "add-challenge", str(comp_dir),
                "--name", "Browser receipt", "--category", "crypto", "--points", "1",
                "--challenge-id", "THEME3", "--difficulty", "Easy",
                "--description", "Authenticated UI receipt fixture",
            )
            receipt_artifact = root / "receipt-artifact.txt"
            receipt_flag = "flag{ui-receipt-test-only}"
            receipt_artifact.write_text(receipt_flag, encoding="utf-8")
            receipt_case = comp_dir / "cases" / "cTHEME3"
            run(
                str(HERE / "case_manager.py"), "scan-flags", str(receipt_case),
                str(receipt_artifact), "--store",
            )
            receipt_data = json.loads((receipt_case / "case.json").read_text(encoding="utf-8"))
            receipt_candidate = receipt_data["candidates"][0]["id"]
            run(
                str(HERE / "case_manager.py"), "candidate", str(receipt_case),
                receipt_candidate, "validated", "--note", "UI receipt fixture validated",
            )
            receipt = run(
                str(HERE / "submitter.py"), "record", str(comp_dir),
                "--challenge", "cTHEME3", "--candidate", receipt_candidate,
                "--outcome", "accepted", "--source", "browser-ui-test",
                "--url", "https://ctf.example/challenges/THEME3",
                "--response-note", "回答正确；已完成；提交记录 1 条",
                "--note", "Synthetic authenticated UI receipt", "--update-case",
            )
            assert '"recorded": true' in receipt.stdout
            submission_text = (comp_dir / "submissions.jsonl").read_text(encoding="utf-8")
            submission_rows = [json.loads(line) for line in submission_text.splitlines() if line]
            receipt_row = submission_rows[-1]
            assert receipt_row["dry_run"] is False
            assert receipt_row["request"]["method"] == "BROWSER_UI"
            assert receipt_row["request"]["body"] == "<flag>"
            assert receipt_row["outcome"] == "accepted"
            assert receipt_flag not in submission_text
            receipt_updated = json.loads((receipt_case / "case.json").read_text(encoding="utf-8"))
            assert receipt_updated["candidates"][0]["status"] == "accepted"
            run(
                str(HERE / "submitter.py"), "record", str(comp_dir),
                "--challenge", "cTHEME3", "--candidate", receipt_candidate,
                "--outcome", "accepted", "--source", "browser-ui-test",
                "--response-note", "回答正确；已完成；提交记录 1 条",
                expected=2,
            )

            session_comp = root / "session-comp"
            session_comp.mkdir()
            run(
                str(HERE / "competition.py"), "init", str(session_comp),
                "--name", "Session CTF", "--scope", "Local authorized fixture",
                "--platform-config", str(session_platform_config(server.server_port, root)),
                "--rate-limit", "min_interval_seconds=0,max_per_window=20,window_seconds=300",
            )
            run(
                str(HERE / "competition.py"), "add-challenge", str(session_comp),
                "--name", "Session challenge", "--category", "web",
                "--challenge-id", "THEME2", "--description", "Session fixture",
            )
            session_artifact = root / "session-artifact.txt"
            session_artifact.write_text("flag{session-test-only}", encoding="utf-8")
            session_case = session_comp / "cases" / "cTHEME2"
            run(
                str(HERE / "case_manager.py"), "scan-flags", str(session_case),
                str(session_artifact), "--store",
            )
            session_data = json.loads((session_case / "case.json").read_text(encoding="utf-8"))
            session_candidate = session_data["candidates"][0]["id"]
            run(
                str(HERE / "case_manager.py"), "candidate", str(session_case),
                session_candidate, "validated", "--note", "Session fixture validated",
            )
            run(
                str(HERE / "submitter.py"), "submit", str(session_comp),
                "--challenge", "cTHEME2", "--flag", "flag{session-test-only}",
                "--candidate", session_candidate,
            )
            os.environ["CTF_SESSION_TEST_CREDS"] = json.dumps({
                "username": "fixture-user", "password": "fixture-pass",
            })
            try:
                session_live = run(
                    str(HERE / "submitter.py"), "submit", str(session_comp),
                    "--challenge", "cTHEME2", "--flag", "flag{session-test-only}",
                    "--candidate", session_candidate, "--live", "--update-case",
                )
            finally:
                os.environ.pop("CTF_SESSION_TEST_CREDS", None)
            assert '"outcome": "accepted"' in session_live.stdout
            assert FlagHandler.session_cookies[-1] == "session=fixture-session"
            assert FlagHandler.requests[-1][0] == "/api/v1/challenges/THEME2/attempt"
            session_updated = json.loads((session_case / "case.json").read_text(encoding="utf-8"))
            assert any(item["status"] == "accepted" for item in session_updated["candidates"])
        finally:
            server.shutdown()
            server.server_close()

    print("OK: triage, case state, flag scan, validation, knowledge search, competition, submitter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
