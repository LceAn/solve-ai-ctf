# Triage and Routing

## Contents

1. Intake checklist
2. Safe artifact triage
3. Category evidence
4. Hybrid routing
5. Initial hypothesis ladder
6. Triage exit criteria

## 1. Intake checklist

Capture:

- challenge and platform IDs;
- supplied category, difficulty, points, solve count, and time remaining;
- description in original language plus exact formatting hints;
- local artifacts with immutable SHA-256 hashes;
- live endpoints and expiry times;
- flag format and case sensitivity;
- known checker or submission rules;
- authorization scope;
- environment constraints, especially network and architecture.

Preserve the original archive. Extract into a new directory and reject absolute paths, `..` traversal, device files, and symlinks escaping the destination.

## 2. Safe artifact triage

Do not execute files during intake. Collect:

- extension and magic bytes;
- size and cryptographic hash;
- archive member names without extraction when possible;
- printable strings and high-value indicators;
- ELF/PE/Mach-O architecture and dynamic dependencies;
- source language and imported libraries;
- image dimensions/metadata;
- filesystem or packet-capture signatures;
- entropy by region for packed/encrypted data;
- adjacent config, Docker, dependency, and model files.

Treat file extensions as hints. A `.txt` may be a key, packet, script, or encoded binary. A challenge-provided executable may be accompanied by a protocol implementation that is more informative than disassembly.

## 3. Category evidence

### Web

Signals: URL, HTTP transcript, cookies, JWT, templates, route code, Flask/Django/Express/PHP, proxy/WAF, GraphQL, upload or object storage.

Initial tools: request capture, route/JS enumeration, normalization diffing, auth-state model, source review, controlled parameter testing.

### Pwn

Signals: ELF, supplied libc/loader, `nc` endpoint, menu protocol, core dump, seccomp, allocator calls, custom serialization.

Initial tools: file/checksec, imports/strings, disassembly, protocol reconstruction, local harness, allocator and libc identification.

### Crypto

Signals: large integers, modular arithmetic, encryption code, ciphertext/key material, PRNG, custom encoding, mathematical parameter bounds.

Initial tools: exact equation extraction, bit-size table, invariant/bound analysis, standard attack decision tree, small test vectors.

### Reverse

Signals: native binary without obvious memory-corruption interaction, APK/DEX, driver, bytecode, custom protocol or verifier.

Initial tools: strings/imports, decompiler, call graph from input to success condition, dynamic hooks, symbolic or constraint solving only after narrowing.

### Forensics

Signals: PCAP/PCAPNG, disk/memory image, office/PDF/image/audio, logs, deleted files, filesystem magic, many small encoded records.

Initial tools: timelines, protocol statistics, carved file signatures, filesystem metadata, metadata extraction, chunk/stride analysis.

### Misc

Signals: layered encodings, puzzles, unusual alphabets, interactive computation, RAID, QR/barcode, language relationships, no dominant category.

Initial tools: representation census, transformation graph, entropy/charset/length deltas, known headers, constraint modeling.

### AI security

Signals: model endpoint, classifier, prompt/tool agent, model weights, embeddings, training/inference data, adversarial objective.

Initial tools: threat model, query budget, input/output schema, deterministic baseline, attack-surface mapping. Do not route to AI security merely because an LLM is solving the task.

## 4. Hybrid routing

Common hybrids:

- Crypto + Pwn: recover model/key/input first, then exploit the service.
- Reverse + Crypto: reverse protocol or key derivation before decryption.
- Forensics + Misc: recover a stream, then traverse an encoding/archive chain.
- Web + Reverse: inspect bundled JavaScript, mobile client, or custom parser.
- Web + Cloud: authorization plus object-store or internal-service assumptions.
- Pwn + Serialization: reconstruct protobuf/custom frames before allocator work.
- AI/ML + Pwn: derive an input satisfying a model, then trigger memory/control flow.

Route the next step by the current bottleneck, not by the platform category.

## 5. Initial hypothesis ladder

Build layers:

1. **Direct disclosure or intended fast path**: strings, source, metadata, supplied keys, RWX shellcode path, weak seed range.
2. **Representation mismatch**: encoding, newline, endian, padding, URL normalization, parser disagreement.
3. **State/auth flaw**: stale pointer, missing used check, role/object mismatch, session signing, workflow trust.
4. **Mathematical/systemic flaw**: PRNG recovery, small-root bounds, allocator invariant, filesystem parity.
5. **Complex chain**: FSOP, multi-stage object storage, chained encodings, adversarial model optimization.

Test the cheap layers first unless evidence strongly points to a deeper mechanism.

## 6. Triage exit criteria

Triage is complete when the case has:

- immutable artifact inventory;
- one primary and optional secondary category with reasons;
- environment/architecture facts;
- flag format;
- 3–7 ranked hypotheses;
- the cheapest next experiment for the top hypothesis;
- explicit unknowns and required tools;
- no execution of untrusted code outside isolation.
