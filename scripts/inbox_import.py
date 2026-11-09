"""半接入比赛（仅附件）导入器：inbox/ 顶层条目 → 题目 + case + 附件入库。

场景：平台登录不在自己手里（队友下载 / 离线复盘赛），只拿到一批附件。
约定（README「半接入比赛」节）：
    比赛/<name>/inbox/
    ├── BabyBlog.zip        # 顶层一个条目 = 一道题；文件名即题名
    ├── EzCalc/             # 目录也行：内含多附件 + README.md（题面前 500 字）
    │   ├── README.md
    │   └── calc.py
    └── EzCalc.meta.json    # 可选：{category, points, description, difficulty}

行为：
- 幂等：已注册 slug / 同名同哈希附件直接跳过（重跑只导新题）
- 分类猜测（可被 meta.json 覆盖）：扩展名映射，猜不中给 misc
- 全程留痕：challenge_registered / case_initialized / artifact_added 进 events
- stdout 末行输出 JSON：{ok, imported, skipped[], failed[]}

用法：
    python scripts/inbox_import.py 比赛/xxx [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

# 扩展名 → 类别猜测（保守：只认强信号扩展名，猜不中 misc，导入后可在工作台改）
CAT_BY_EXT = {
    ".pcap": "forensics", ".pcapng": "forensics",
    ".apk": "reverse", ".exe": "reverse", ".dll": "reverse", ".so": "reverse",
    ".elf": "reverse",
    ".html": "web", ".php": "web",
    ".sage": "crypto", ".rsa": "crypto",
}
DESC_FILES = ("readme.md", "题面.md", "description.md", "readme.txt", "readme")


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name).strip("-").lower()
    return s[:48] or "chall"


def guess_category(entry: Path) -> str:
    if entry.is_file():
        return CAT_BY_EXT.get(entry.suffix.lower(), "misc")
    exts = {f.suffix.lower() for f in entry.rglob("*") if f.is_file()}
    hits = {CAT_BY_EXT[e] for e in exts if e in CAT_BY_EXT}
    # 全部附件指向同一类才定，否则 misc（混合附件常见于 misc 题）
    return hits.pop() if len(hits) == 1 else "misc"


def read_desc(entry: Path) -> str:
    """目录题：取 README/题面 前 500 字作描述；文件题留空。"""
    if not entry.is_dir():
        return ""
    for cand in DESC_FILES:
        p = entry / cand
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace").strip()[:500]
            except OSError:
                continue
    return ""


def load_meta(inbox: Path, stem: str) -> dict:
    p = inbox / f"{stem}.meta.json"
    if not p.is_file():
        return {}
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def run(argv: list[str]) -> tuple[int, str]:
    r = subprocess.run([sys.executable, *[str(a) for a in argv]],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def import_one(comp: Path, entry: Path, meta: dict) -> tuple[str, dict]:
    """导入单个顶层条目。返回 (状态, 详情)：imported | skipped | failed。"""
    stem = entry.name if entry.is_file() else entry.name
    slug = str(meta.get("slug") or slugify(Path(stem).stem))
    name = str(meta.get("name") or Path(stem).stem)
    cfg_path = comp / "competition.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if any(c.get("slug") == slug for c in cfg.get("challenges", [])):
        return "skipped", {"slug": slug, "reason": "already registered"}

    category = str(meta.get("category") or guess_category(entry))
    argv = [SCRIPTS / "competition.py", "add-challenge", comp,
            "--name", name, "--category", category, "--slug", slug]
    if meta.get("description") or read_desc(entry):
        argv += ["--description", str(meta.get("description") or read_desc(entry))]
    if meta.get("points") is not None:
        argv += ["--points", str(meta["points"])]
    if meta.get("difficulty"):
        argv += ["--difficulty", str(meta["difficulty"])]
    code, out = run(argv)
    if code != 0:
        return "failed", {"slug": slug, "error": out.strip()[-200:]}

    case_dir = comp / "cases" / slug
    if not (case_dir / "case.json").exists():
        code, out = run([SCRIPTS / "case_manager.py", "init", case_dir,
                         "--name", name, "--category", category])
        if code != 0:
            return "failed", {"slug": slug, "error": out.strip()[-200:]}

    # 附件入库：目录题整目录搬，文件题单文件搬
    files = sorted(entry.rglob("*")) if entry.is_dir() else [entry]
    files = [f for f in files if f.is_file() and f.name != f"{Path(stem).stem}.meta.json"]
    art_count = 0
    for f in files:
        code, out = run([SCRIPTS / "case_manager.py", "artifact-add", case_dir,
                         "--file", f, "--source", "inbox"])
        if code == 0:
            art_count += 1
    return "imported", {"slug": slug, "name": name, "category": category,
                        "artifacts": art_count}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comp_dir", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="只列将要导入的条目，不动任何文件")
    args = ap.parse_args()

    comp = args.comp_dir.resolve()
    inbox = comp / "inbox"
    if not comp.is_dir():
        print(f"比赛目录不存在：{comp}", file=sys.stderr)
        return 2
    if not inbox.is_dir():
        print(json.dumps({"ok": True, "imported": 0, "skipped": [],
                          "failed": [], "note": "inbox/ 不存在（把附件放进 比赛/<name>/inbox/ 后重跑）"},
                         ensure_ascii=False))
        return 0

    entries = sorted(p for p in inbox.iterdir()
                     if not p.name.startswith(".") and not p.name.endswith(".meta.json"))
    imported, skipped, failed = [], [], []
    for entry in entries:
        if args.dry_run:
            imported.append({"slug": slugify(Path(entry.name).stem), "entry": entry.name,
                             "category": guess_category(entry)})
            continue
        try:
            status, detail = import_one(comp, entry, load_meta(inbox, Path(entry.name).stem))
        except Exception as exc:  # noqa: BLE001
            status, detail = "failed", {"slug": entry.name, "error": str(exc)[:200]}
        ({"imported": imported, "skipped": skipped, "failed": failed}[status]).append(detail)
        # 导入成功后移走原件（挪进 inbox/.done/ 留档，不删——附件是原始证据）
        if status == "imported":
            done = inbox / ".done"
            done.mkdir(exist_ok=True)
            dest = done / entry.name
            n = 1
            while dest.exists():
                dest = done / f"{entry.stem}-{n}{entry.suffix}"
                n += 1
            shutil.move(str(entry), str(dest))

    print(json.dumps({"ok": not failed, "imported": imported,
                      "skipped": skipped, "failed": failed,
                      "dry_run": args.dry_run}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
