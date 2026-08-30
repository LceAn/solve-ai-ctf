# Pwn Playbook

## Contents

1. Intake
2. Protocol reconstruction
3. Vulnerability and primitive matrix
4. Modern glibc workflow
5. Control-flow strategy
6. Reliability engineering
7. Stop and pivot rules

## 1. Intake

Record:

- architecture, endianness, interpreter, libc and loader;
- PIE, NX, canary, RELRO, CET, FORTIFY;
- seccomp policy and available syscalls;
- imports, allocator functions, fixed mappings, global arrays;
- local/remote protocol and buffering;
- supplied source, symbols, model/data files, or custom serialization library.

Use the supplied loader and libc for local reproduction. Hash every binary/library. Do not apply offsets from a different build.

Check for the intended fast path first: executable mapping, direct function pointer call, exposed address, magic value, or a simple overflow. One HK SeCAI task was solved by sending shellcode to an RWX mapping; complex ROP would have wasted time.

## 2. Protocol reconstruction

Build a deterministic client before exploitation. For custom binary/protobuf protocols, write explicit encoders/decoders and assert each response boundary.

Capture:

- frame length and endian;
- fields, tags, types, and size constraints;
- menu state and indices;
- whether operations check allocation/used state consistently;
- exact read lengths and whether partial writes block;
- server prompts and response framing.

Do not use broad `clean()` or timing sleeps when strict synchronization is possible. Network desynchronization can masquerade as exploit failure.

## 3. Vulnerability and primitive matrix

Translate bugs into primitives:

| Bug | Read primitive | Write primitive | Constraint |
|---|---|---|---|
| delete does not clear pointer | UAF show | UAF edit | used checks may differ |
| size confusion | over-read | overflow | signedness and read loop |
| format string | stack/libc leak | `%n` write | argument offset |
| stack overflow | stack leak optional | return overwrite | canary/NX/PIE |
| double free | allocator metadata | tcache control | duplicate checks |

For each primitive, record address knowledge, size/alignment, number of uses, null-byte behavior, and whether the operation consumes allocator state.

## 4. Modern glibc workflow

Identify the exact libc version before selecting a heap technique.

### Safe-linking

For tcache next pointers:

`encoded = (storage_position >> 12) XOR target`

Do not say “safe-linking bypassed” without showing how the storage position or key is learned, constrained, or probabilistically guessed.

Useful evidence patterns:

- a single-entry tcache chunk exposes `chunk_addr >> 12` when readable;
- two related encoded links may reveal a chunk address;
- a partial overwrite may be feasible but must include success probability and restart budget;
- allocator/user-copy side effects may consume or overwrite the same bin.

### Version-specific allocation paths

Inspect the actual implementation. `calloc` and `malloc` may differ in tcache fast-path checks and clearing behavior. In one corpus case, a modern `calloc` path made allocation to a fixed writable mapping possible without a conventional fake header. Generalize only after verifying the target libc.

### Libc leaks

Options include unsorted-bin metadata, FILE structures, GOT/PLT, dynamic linker structures, or an existing pointer. Account for `%s` truncation and preserve exact leaked bytes.

### Hooks and FSOP

Modern glibc removed or hardened common hooks. Consider GOT writes only with suitable RELRO and PIE knowledge. For FSOP/House-of-Apple-style chains:

- verify structure offsets against the supplied libc;
- check wide-data and vtable invariants;
- confirm every gadget lies in an executable segment;
- build a minimal local trigger before remote retries;
- treat post-competition chains as unverified until reproduced.

## 5. Control-flow strategy

Choose the simplest viable goal:

1. Direct shellcode if executable memory and syscalls permit it.
2. Return-to-win or magic write.
3. ret2libc/system when allowed.
4. ORW ROP under seccomp.
5. Stack pivot or setcontext.
6. FSOP only when simpler primitives are unavailable.

Parse seccomp instead of guessing. For ORW, determine path, syscall availability, file descriptor handling, writable buffer, and output channel. If `open` returns an unknown fd, use a gadget/sequence that moves `rax` to the fd argument or control the fd by closing a known descriptor.

## 6. Reliability engineering

- Use local/remote/GDB modes with one protocol implementation.
- Pin libc, loader, environment, and timeouts.
- Replace sleeps with expected prompt/length reads.
- Send exact required lengths; detect blocking reads.
- Validate leaks with canonical-address and alignment checks.
- Assert derived bases and target mappings.
- Log attempt number and probabilistic phase separately.
- Make retries restart from a clean process/container.
- Keep exploit output machine-parseable and scan it for candidate flags.

For probabilistic exploits, report probability per attempt and cumulative success probability. A 1/256 partial-overwrite path needs a controlled retry budget and reliable failure detection.

## 7. Stop and pivot rules

Pivot when:

- the technique assumes the wrong libc version;
- a leak is not reproducible or derived bases fail alignment/range checks;
- crashes occur before the intended primitive due to protocol desync;
- allocator side effects invalidate the tcache model;
- a gadget is outside executable memory;
- retries have no reliable success/failure oracle.

Before escalating to FSOP, re-check fixed mappings, writable globals, GOT, stack targets, direct function calls, and the intended win condition.
