# HK SeCAI 2026 Case Pattern Corpus

## Contents

1. Corpus scope and caveats
2. Evidence-derived patterns
3. Failure patterns
4. Capability implications
5. Source map

## 1. Corpus scope and caveats

This corpus distills the local HK SeCAI 2026 materials. It intentionally omits real flags, credentials, live platform details, and reusable secrets.

The records contain contradictions across time. The competition summary marks one Pwn task unsolved during the event, while later files describe a complete post-event chain. Another Reverse writeup is only a high-level account without a reproduced IOCTL or flag. Therefore every pattern must retain:

- source file;
- phase: `pre_match`, `during_competition`, or `post_competition`;
- verification: `reproduced`, `platform_accepted`, `reported`, or `unverified`;
- confidence and missing evidence.

The actual event set was dominated by traditional CTF categories solved by AI-assisted workflows. Pre-match forecasts expected a distinct AI-security category, but the recorded challenge list did not expose one. Build the solver around general CTF competence; keep AI security as an optional domain.

## 2. Evidence-derived patterns

### Small PRNG seed + permutation inversion

- Category: Crypto
- Mechanism: a sub-million seed space drives an in-place shuffle.
- Decisive method: replay shuffle on indices, invert the permutation, and use decoded structure as a fast reject.
- General lesson: model library semantics exactly; brute force can be the optimal attack when bounded and verified.
- Confidence: high; complete solve script and writeup exist.

### Approximate multiple of RSA phi

- Category: Crypto
- Mechanism: a small multiplier times `phi(N)` plus a bounded error leaks enough approximation for a small-root attack.
- Decisive method: enumerate the multiplier, derive the error bound and factor approximation, use lattice/Coppersmith, verify `N % p == 0`.
- General lesson: bit-size/bound analysis selects the attack; “looks close” is not sufficient.
- Confidence: high for the reported method; preserve Sage version and validate the polynomial in future use.

### CBC partial decryption + MT19937 cloning

- Category: Crypto
- Mechanism: known key decrypts all CBC blocks after block zero despite unknown IV; plaintext exposes enough consecutive MT outputs to clone state.
- General lesson: composition leaks can turn an unknown IV into a recoverable PRNG state problem.
- Caveat: unit-test word ordering and untemper logic; prose implementations can contain subtle errors.
- Confidence: high conceptually; verify any reused implementation.

### Companion artifacts reveal the whole protocol

- Category: Reverse/Crypto
- Mechanism: packet files included a private key and encrypted key/flag; source documented the exchange; escaped newline representation was the main parsing trap.
- General lesson: inventory and cross-file correlation should precede disassembly.
- Confidence: high; runnable script exists.

### Android dynamic verification bypass

- Category: Reverse
- Mechanism: runtime signature/package verification gates dynamically loaded content.
- General lesson: trace the exact gate and prove behavior with a hook or patch.
- Caveat: the local writeup lacks concrete class/method and reproduction artifacts, so its knowledge quality is medium.

### Windows driver IOCTL reconstruction

- Category: Reverse
- Reported mechanism: reconstruct user-mode/driver communication and correct IOCTL request.
- Caveat: the available writeup is generic and does not include concrete IOCTL, buffer schema, or reproduced output.
- Confidence: low as a reusable case; retain only the triage checklist, not the claimed solve details.

### RAID parity reconstruction

- Category: Forensics/Misc
- Mechanism: recover a missing RAID5 member/data stream using parity and correct layout.
- General lesson: XOR is necessary but member order, parity rotation, stripe size, and filesystem validation determine correctness.
- Caveat: the local summary simplifies reconstruction; do not generalize it into “XOR two disks and mount.”
- Confidence: medium-high for the challenge outcome, medium for the abbreviated method.

### DNS tunnel → custom alphabet → encrypted archive

- Category: Forensics/Misc
- Mechanism: ordered DNS labels carry Base32; output uses a custom Base58 ordering; result is a legacy encrypted ZIP with predictable stored-file header.
- Decisive method: validate every stage by charset, sequence coverage, magic, and archive structure; use known plaintext only after confirming cipher/compression.
- General lesson: preserve a transformation graph and use structural validators at each edge.
- Confidence: high; complete derived artifacts and solve script exist.

### Filesystem residue + fixed-stride hiding

- Category: Forensics
- Mechanism: deleted/residual file bytes contain signal at a regular stride.
- General lesson: after carving, test periodic structure and exact flag case.
- Confidence: high; offset-specific solve is reproduced, but future automation should infer offsets/stride.

### Cross-layer URL canonicalization

- Category: Web
- Mechanism: a security layer and custom parser decode/normalize differently, enabling traversal to a hinted hidden namespace.
- General lesson: construct a parser matrix from architecture clues; one controlled differential beats generic fuzzing.
- Confidence: high; minimal reproducible request exists.

### Direct RWX shellcode path

- Category: Pwn
- Mechanism: process maps writable-executable memory, reads attacker bytes, and calls it without seccomp/filtering.
- General lesson: always test the simplest intended primitive before building ROP.
- Confidence: high; exploit exists.

### Modern `calloc` tcache poisoning

- Category: Pwn
- Mechanism: UAF read/write reveals safe-linking data; a target-version allocation path allows a tcache entry to resolve to a fixed writable mapping; magic write unlocks the flag.
- General lesson: allocator call choice and libc version are part of the vulnerability.
- Confidence: high for the supplied build; never transfer offsets or checks across versions.

### UAF → libc/heap/stack leaks → ORW

- Category: Pwn
- Mechanism: stale pointer supports UAF read/write; unsorted and tcache data provide bases; allocation to `environ` leaks stack; second poisoning writes a seccomp-compatible ORW chain.
- General lesson: express the solve as a sequence of primitives with assertions.
- Confidence: high; detailed writeup and exploit exist.

### Protobuf UAF + probabilistic safe-linking + FSOP

- Category: Pwn
- During-event state: UAF confirmed, leak blocked.
- Post-event claim: partial-overwrite retries lead to heap/libc leaks, then House-of-Apple-style FSOP and ORW.
- General lesson: serialization allocations contaminate heap state; strict request/response synchronization matters; probabilistic exploit budgets must be explicit.
- Confidence: medium until offsets/gadgets are filled and the chain is reproduced cleanly.

## 3. Failure patterns

### Unbounded semantic guessing

One Web task accumulated thousands of profile-key candidates across many workers. Logs repeatedly warned against duplication, yet the same mechanism continued with new combinations.

Failure causes:

- no machine-enforced hypothesis fingerprint;
- candidate coverage was not defined;
- “number of guesses” substituted for information gain;
- workers shared prose rather than transactional state;
- escalation added workers, not a distinct attack surface;
- unreliable JWT cracking output was initially treated as evidence.

Required correction: after a bounded candidate family fails, reject or park the hypothesis, record coverage, and pivot to authorization/state/parser/source/adjacent-service models.

### Generic writeups mistaken for knowledge

Some summaries name tools and broad steps but omit the decisive address, structure, request, equation, or validation. Store these as low-confidence orientation, not solved exemplars.

### Status drift

Challenge lists, live notes, competition summaries, and post-event writeups disagree. Never infer truth from directory names such as `solved/`; use evidence and phase.

### Unsafe monolithic Agent design

The pre-match Agent prototype exposed unrestricted shell execution, used `shell=True`, described Python execution as safe despite weak isolation, truncated outputs, and embedded a single generic submit format. Treat it as a prototype, not production architecture.

## 4. Capability implications

Prioritize the following investments:

1. Evidence/state engine and attempt deduplication.
2. Safe triage and cross-artifact correlation.
3. Web parser/auth/workflow modeling—the weakest event category.
4. Modern glibc version-aware knowledge and reliable protocol clients.
5. Crypto bounds/PRNG exactness with deterministic verifiers.
6. Forensics transformation graphs and layout enumeration.
7. Dedicated submitter and platform adapters.
8. Benchmarking against both solved and unsolved cases.
9. Knowledge provenance and contradiction handling.
10. Offline isolation and deterministic fallback tools.

## 5. Source map

Primary local sources:

- `_archive/pre_match/自动答题实现报告.md`
- `_archive/pre_match/knowledge_base/08_AI_CTF自动化解题Agent.md`
- `_archive/pre_match/knowledge_base/10_Agent工程设计与运行手册.md`
- `_archive/pre_match/knowledge_base/11_题型自动化Playbook.md`
- `_archive/pre_match/knowledge_base/12_离线环境与工具清单.md`
- `比赛文档/CHALLENGES.md`
- `比赛文档/比赛总结报告.md`
- `CTF框架/AutoSolver自动化框架设计.md`
- `CTF框架/多Agent协作协议.md`
- per-challenge Markdown writeups and solve scripts under `比赛文档/challs/`

Treat platform credentials and real flags found in those sources as sensitive local data; do not copy them into reusable skill content.
