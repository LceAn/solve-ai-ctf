# Offline Environment and Isolation

## Contents

1. Readiness levels
2. Core tool matrix
3. Isolation
4. Offline assets
5. Preflight
6. Fallbacks

## 1. Readiness levels

- **L0 Inventory**: Python, hashing, archive listing, strings, file identification.
- **L1 Core CTF**: HTTP tooling, pwntools, Crypto, Z3, packet/filesystem utilities.
- **L2 Specialist**: SageMath, Ghidra/rizin, GDB plugin, Volatility, bkcrack, mobile tooling, ML attack libraries.
- **L3 Autonomous**: local/remote LLM adapter, sandbox runner, case store, scheduler, submitter, observability, benchmark suite.

Declare the achieved level per machine. A missing specialist tool should route to a fallback or mark a blocker, not cause silent failure.

## 2. Core tool matrix

Suggested capabilities:

- Common: Python 3, Git, curl, jq, file, strings, xxd, openssl, 7z/unzip, ripgrep.
- Web: HTTP client/proxy, ffuf/dirsearch, sqlmap/nuclei where authorized, JWT/session utilities.
- Pwn: pwntools, checksec, GDB + pwndbg/gef, ROPgadget/ropper, patchelf, seccomp tools.
- Crypto: PyCryptodome, gmpy2, sympy, SageMath, RsaCtfTool, hashcat/john.
- Reverse: Ghidra, rizin/radare2, jadx/apktool, Frida, angr, Z3, Windows VM/WinDbg for drivers.
- Forensics: tshark/Wireshark, binwalk, exiftool, sleuthkit, Volatility 3, foremost, zsteg/steghide, bkcrack.
- AI security: NumPy/PyTorch, ART/cleverhans or equivalent, prompt/model evaluation harnesses as required.

Pin versions in an image/lockfile and preserve installers or package caches for offline use.

## 3. Isolation

Use disposable containers/VMs for challenge code and binaries. Apply:

- unprivileged user;
- read-only original artifacts;
- writable per-case output directory;
- CPU, memory, process, and wall-clock limits;
- network disabled by default, then allow only authorized target ranges;
- no host credentials, SSH agent, cloud metadata, home directory, or Docker socket;
- syscall/profile restrictions appropriate to the analysis tool;
- process-tree termination on timeout.

Containerization is not enough for hostile kernel modules or VM escapes. Use a dedicated VM for drivers and high-risk native artifacts.

## 4. Offline assets

Prepare:

- common wordlists and challenge-specific dictionaries;
- libc/loader collection with build IDs;
- Ghidra processors/scripts and decompiler caches;
- Sage, Python wheels, package caches, and container images;
- symbols and reference docs;
- packet/file signatures and custom alphabet utilities;
- local LLM weights/runtime if required;
- platform adapter templates with placeholders, never real credentials;
- a synthetic offline benchmark pack.

Inventory each asset with version, hash, license, and tested command.

## 5. Preflight

Run before the event and after any machine move:

1. Verify free disk/RAM/CPU and system clock.
2. Import critical Python modules.
3. Execute version checks for tools.
4. Run a tiny known-good sample for HTTP, ELF, crypto, PCAP, and archive handling.
5. Start/stop the isolation environment.
6. Confirm authorized target routing and DNS behavior.
7. Exercise platform adapter in dry-run or staging.
8. Run `python3 scripts/self_test.py`.
9. Reboot and repeat the critical path.

Do not let a preflight script write wordlists or dependencies into the user’s home without explicit intent. Checks should be read-only by default.

## 6. Fallbacks

- No remote LLM: local model → deterministic playbook → park complex cases.
- No Sage: attempt standard integer attacks; preserve equations and mark lattice blocker.
- No Ghidra: use rizin/objdump/strings and dynamic tracing.
- No pwntools: use sockets and `struct` for simple protocols.
- No packet GUI: use tshark/scapy scripts.
- No mount privileges: use filesystem parsers/carvers in user space.
- Tool reports inconsistent results: validate with a second implementation or a minimal known-good fixture.
