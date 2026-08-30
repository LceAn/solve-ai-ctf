#!/usr/bin/env python3
"""Offline self-test for the bundled deterministic CTF utilities."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
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

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        self.__class__.requests.append((self.path, body))
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

            reg_case = comp_dir / "cases" / "synthetic"
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
                "--challenge", "synthetic", "--flag", "flag{synthetic-test-only}",
                "--candidate", reg_candidate,
            )
            assert "dry-run" in dry.stdout

            live = run(
                str(HERE / "submitter.py"), "submit", str(comp_dir),
                "--challenge", "synthetic", "--flag", "flag{synthetic-test-only}",
                "--candidate", reg_candidate, "--live", "--update-case",
            )
            assert '"outcome": "accepted"' in live.stdout
            assert len(FlagHandler.requests) == 1
            assert "competitionId=CID1" in FlagHandler.requests[0][1]
            assert "ctfThemeId=THEME1" in FlagHandler.requests[0][1]

            run(
                str(HERE / "submitter.py"), "submit", str(comp_dir),
                "--challenge", "synthetic", "--flag", "flag{synthetic-test-only}",
                expected=2,
            )

            run(str(HERE / "submitter.py"), "history", str(comp_dir))
            run(str(HERE / "submitter.py"), "rate", str(comp_dir))
            updated = json.loads((reg_case / "case.json").read_text(encoding="utf-8"))
            assert any(item["status"] == "accepted" for item in updated["candidates"])
        finally:
            server.shutdown()
            server.server_close()

    print("OK: triage, case state, flag scan, validation, knowledge search, competition, submitter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
