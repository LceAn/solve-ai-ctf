#!/usr/bin/env python3
"""Static, non-executing triage for authorized CTF artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAGIC = [
    (b"\x7fELF", "ELF executable"),
    (b"MZ", "PE executable"),
    (b"PK\x03\x04", "ZIP/OOXML archive"),
    (b"\x1f\x8b", "gzip archive"),
    (b"7z\xbc\xaf\x27\x1c", "7z archive"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"%PDF", "PDF document"),
    (b"SQLite format 3\x00", "SQLite database"),
    (b"\xd4\xc3\xb2\xa1", "PCAP capture"),
    (b"\xa1\xb2\xc3\xd4", "PCAP capture"),
    (b"\x0a\x0d\x0d\x0a", "PCAPNG capture"),
    (b"\xeb\x52\x90NTFS    ", "NTFS filesystem image"),
    (b"\xed\xab\xee\xdb", "RPM package"),
    (b"dex\n", "Android DEX"),
]

EXTENSION_WEIGHTS: dict[str, dict[str, int]] = {
    ".pcap": {"forensics": 8}, ".pcapng": {"forensics": 8},
    ".mem": {"forensics": 7}, ".dmp": {"forensics": 7},
    ".img": {"forensics": 5, "misc": 2}, ".raw": {"forensics": 4},
    ".apk": {"reverse": 8}, ".dex": {"reverse": 7}, ".smali": {"reverse": 6},
    ".sys": {"reverse": 7, "pwn": 2}, ".so": {"pwn": 5, "reverse": 3},
    ".sage": {"crypto": 8}, ".pem": {"crypto": 5}, ".key": {"crypto": 4},
    ".onnx": {"ai_security": 8}, ".pt": {"ai_security": 7},
    ".pth": {"ai_security": 7}, ".npy": {"ai_security": 5},
    ".wasm": {"reverse": 6}, ".class": {"reverse": 5}, ".jar": {"reverse": 5},
    ".php": {"web": 6}, ".html": {"web": 3}, ".js": {"web": 4},
}

TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".pyw", ".sage", ".js", ".ts", ".html", ".htm",
    ".php", ".rb", ".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".java",
    ".smali", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".csv",
}

PATH_CATEGORY_HINTS = {
    "web": "web", "pwn": "pwn", "crypto": "crypto", "reverse": "reverse",
    "rev": "reverse", "misc": "misc", "forensics": "forensics", "forensic": "forensics",
    "ai": "ai_security", "ml": "ai_security",
}

KEYWORDS: dict[str, tuple[str, ...]] = {
    "web": ("http", "flask", "django", "express", "jwt", "cookie", "route", "werkzeug", "graphql", "minio", "template", "session"),
    "pwn": ("glibc", "libc.so", "seccomp", "malloc", "calloc", "free(", "buffer overflow", "tcache", "rop", "pwntools", "nc "),
    "crypto": ("rsa", "aes", "cipher", "encrypt", "decrypt", "modulus", "getprime", "getrandbits", "mt19937", "coppersmith", "nonce", "randrange", "seed(", "shuffle("),
    "reverse": ("decompile", "disassemble", "frida", "jadx", "driverentry", "deviceiocontrol", "ioctl", "ghidra", "angr", "correct!"),
    "forensics": ("pcap", "ntfs", "volatility", "wireshark", "deleted file", "disk image", "dns tunnel", "exif", "stegan"),
    "misc": ("base32", "base58", "base64", "morse", "raid", "qr", "puzzle", "riddle", "custom alphabet"),
    "ai_security": ("prompt injection", "adversarial", "classifier", "model extraction", "membership inference", "embedding", "pytorch", "tensorflow"),
}

FLAG_RE = re.compile(rb"(?i)(?:flag|hkcert|ctf)\{[^}\r\n]{1,256}\}")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample_bytes(path: Path, limit: int = 1024 * 1024) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= limit:
            return handle.read()
        half = limit // 2
        head = handle.read(half)
        handle.seek(max(size - half, 0))
        return head + handle.read(half)


def magic_type(data: bytes, suffix: str) -> str:
    for signature, label in MAGIC:
        if data.startswith(signature):
            return label
    if data.startswith((b"#!", b"import ", b"from ")) and suffix == ".py":
        return "Python source"
    if data[:1] in (b"{", b"["):
        try:
            json.loads(data[:200_000].decode("utf-8"))
            return "JSON data"
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    return "unknown"


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    printable = sum(1 for byte in data if byte in b"\t\n\r" or 32 <= byte <= 126)
    return printable / len(data)


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def analyze_file(path: Path, root: Path) -> dict[str, Any]:
    stat = path.lstat()
    record: dict[str, Any] = {
        "path": safe_relative(path, root),
        "size": stat.st_size,
        "suffix": path.suffix.lower(),
        "symlink": path.is_symlink(),
    }
    if path.is_symlink():
        record["warning"] = "symlink not followed"
        return record
    try:
        sample = sample_bytes(path)
        record.update({
            "sha256": sha256_file(path),
            "magic": magic_type(sample, path.suffix.lower()),
            "sample_entropy": round(entropy(sample), 3),
            "sample_printable_ratio": round(printable_ratio(sample), 3),
            "flag_like_count": len(set(FLAG_RE.findall(sample))),
        })
        matched: dict[str, list[str]] = {}
        if path.suffix.lower() in TEXT_SUFFIXES or (record["sample_printable_ratio"] >= 0.7 and b"\x00" not in sample[:4096]):
            text = sample.decode("utf-8", errors="ignore").lower()
            for category, words in KEYWORDS.items():
                hits = sorted({word for word in words if word in text})
                if hits:
                    matched[category] = hits[:12]
        record["keyword_hits"] = matched
    except (OSError, PermissionError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def collect_paths(target: Path) -> tuple[Path, list[Path]]:
    if not target.exists() and not target.is_symlink():
        raise FileNotFoundError(target)
    if target.is_file() or target.is_symlink():
        return target.parent, [target]
    paths = [path for path in target.rglob("*") if path.is_file() or path.is_symlink()]
    return target, sorted(paths, key=lambda p: str(p).lower())


def classify(files: list[dict[str, Any]], target: Path) -> dict[str, Any]:
    scores: defaultdict[str, int] = defaultdict(int)
    reasons: defaultdict[str, list[str]] = defaultdict(list)
    path_words = set(re.findall(r"[a-z]+", str(target).lower()))
    for word, category in PATH_CATEGORY_HINTS.items():
        if word in path_words:
            scores[category] += 8
            reasons[category].append(f"path metadata: {word}")
    for item in files:
        suffix = item.get("suffix", "")
        for category, weight in EXTENSION_WEIGHTS.get(suffix, {}).items():
            scores[category] += weight
            reasons[category].append(f"{item['path']}: extension {suffix}")
        magic = item.get("magic", "")
        if magic == "ELF executable":
            scores["pwn"] += 7
            scores["reverse"] += 4
            reasons["pwn"].append(f"{item['path']}: ELF")
        elif magic == "PE executable":
            scores["reverse"] += 7
            reasons["reverse"].append(f"{item['path']}: PE")
        elif "PCAP" in magic or "filesystem" in magic:
            scores["forensics"] += 8
            reasons["forensics"].append(f"{item['path']}: {magic}")
        for category, hits in item.get("keyword_hits", {}).items():
            scores[category] += min(len(hits), 5)
            reasons[category].append(f"{item['path']}: {', '.join(hits[:5])}")
    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    primary = ranked[0][0] if ranked and ranked[0][1] > 0 else "misc"
    secondary = None
    if len(ranked) > 1 and ranked[1][1] >= max(3, ranked[0][1] * 0.55):
        secondary = ranked[1][0]
    return {
        "primary": primary,
        "secondary": secondary,
        "scores": dict(ranked),
        "reasons": {key: value[:10] for key, value in reasons.items()},
    }


def triage(target: Path) -> dict[str, Any]:
    root, paths = collect_paths(target)
    files = [analyze_file(path, root) for path in paths]
    warnings = []
    if any(item.get("symlink") for item in files):
        warnings.append("Symlinks were recorded but not followed.")
    if any(item.get("flag_like_count", 0) for item in files):
        warnings.append("Flag-like text exists in artifacts; treat it as an unverified candidate or fixture.")
    return {
        "schema_version": 1,
        "generated_at": utcnow(),
        "target": str(target.resolve()),
        "root": str(root.resolve()),
        "execution_policy": "static-only; no artifact executed or archive extracted",
        "file_count": len(files),
        "classification": classify(files, target),
        "warnings": warnings,
        "files": files,
    }


def render_markdown(report: dict[str, Any]) -> str:
    cls = report["classification"]
    lines = [
        "# CTF Static Triage",
        "",
        f"- Target: `{report['target']}`",
        f"- Files: {report['file_count']}",
        f"- Primary route: **{cls['primary']}**",
        f"- Secondary route: **{cls['secondary'] or 'none'}**",
        f"- Policy: {report['execution_policy']}",
        "",
    ]
    if report["warnings"]:
        lines += ["## Warnings", ""] + [f"- {warning}" for warning in report["warnings"]] + [""]
    lines += ["## Category scores", ""]
    for category, score in cls["scores"].items():
        lines.append(f"- {category}: {score}")
    lines += ["", "## Files", "", "| Path | Size | Magic | SHA-256 |", "|---|---:|---|---|"]
    for item in report["files"]:
        sha = item.get("sha256", "-")
        lines.append(f"| `{item['path']}` | {item['size']} | {item.get('magic', item.get('warning', '-'))} | `{sha}` |")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--compact", action="store_true", help="Print compact JSON instead of Markdown")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = triage(args.target)
    except (OSError, FileNotFoundError) as exc:
        print(f"triage error: {exc}", file=sys.stderr)
        return 2
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown + "\n", encoding="utf-8")
    if args.compact:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
