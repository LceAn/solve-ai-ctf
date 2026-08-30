# Crypto and Reverse Playbooks

## Contents

1. Crypto modeling
2. Crypto decision patterns
3. PRNG and mode-composition attacks
4. Reverse workflow
5. Mobile and driver targets
6. Constraint and symbolic execution
7. Verification

## 1. Crypto modeling

Rewrite the challenge as exact equations. Create a table of known values, unknowns, bit sizes, ranges, reuse, and observed outputs. Treat code semantics—integer division, byte order, padding, Python random behavior—as part of the cryptosystem.

Before advanced math, test:

- small key/seed/nonce space;
- repeated nonce/keystream;
- weak or recoverable PRNG;
- ECB patterns and CBC/CTR composition mistakes;
- RSA shared modulus/prime, small exponent, low private exponent, partial leakage;
- encoding/permutation mistaken for encryption;
- keys or private material included in companion files.

Always create a verifier: re-encrypt, reproduce the public output, factor-check `p*q=N`, or validate recovered state against known future outputs.

## 2. Crypto decision patterns

### Small state space

If a seed or key has a bounded space, estimate total operations and implement a fast reject condition. For shuffled data, reproduce the permutation on indices and invert it; do not guess how a library mutates the list.

### Approximate RSA leakage

When a value is close to a small multiple of `phi(N)`:

1. Enumerate the small multiplier.
2. Derive the implied approximation and error bound.
3. Relate `phi(N)` to `p+q`.
4. Decide whether direct recovery, lattice/Coppersmith, or another partial-key method fits the bound.
5. Verify any root by divisibility before decrypting.

Do not copy a polynomial from another writeup without checking its algebra and ring semantics. Record `X`, `beta`, modulus, and why the theorem’s conditions plausibly hold.

### RSA checklist

- gcd across moduli and ciphertexts;
- `e`, message size, padding, and broadcast count;
- continued fractions for small `d`;
- known high/low bits or approximate factors;
- faulty signatures/CRT;
- oracle behavior and query limits.

## 3. PRNG and mode-composition attacks

Map every random call to exact generator outputs. Python `getrandbits(128)` consumes four 32-bit MT outputs; byte conversion may pad or change representation.

For CBC with an unknown IV, blocks after the first can still be decrypted with the key because they chain from previous ciphertext blocks. If those blocks contain PRNG output and enough consecutive MT outputs are recovered, clone the state and reconstruct missing context.

State recovery requirements:

- correct output word ordering;
- correct untemper implementation;
- 624 consecutive 32-bit outputs for MT19937 state;
- validation against known later output before trusting recovered earlier/next values;
- explicit treatment of unknown prefix block count.

Prefer a tested MT cloning library or unit-tested bitwise inverse. A plausible but incorrect untemper routine is a common writeup error.

## 4. Reverse workflow

Start from the success condition and work backward:

1. Identify entry points and input channels.
2. Locate strings, compare/decrypt calls, failure/success branches, and protocol handlers.
3. Build a call graph from input to gate.
4. Name functions and data structures.
5. Reimplement the smallest relevant algorithm.
6. Use dynamic hooks or patches only after understanding what is being bypassed.
7. Produce a standalone reproducer.

Inspect companion files first. A captured packet may contain a private key; source may reveal that packet labels are misleading; escaped newlines may need normalization before key import.

## 5. Mobile and driver targets

### Android

- inspect manifest, exported components, assets, native libraries, and dynamic loaders;
- trace signature/package verification and server/asset decryption;
- use static patching or hooks for the exact check;
- confirm whether bypass alone reveals the secret or only unlocks the next stage;
- document class/method and observed behavior, not just “use Frida.”

### Windows drivers

- locate `DriverEntry`, device creation, symbolic link, and dispatch table;
- map IOCTL codes, transfer method, input/output structures, and size checks;
- trace the user-mode client’s `DeviceIoControl` calls;
- isolate driver execution in a disposable Windows VM;
- avoid claiming a complete solution without concrete IOCTL, buffer layout, and reproduced output.

High-level prose without these artifacts has low evidentiary confidence.

## 6. Constraint and symbolic execution

Use Z3 when the verifier can be expressed as bounded constraints. Use symbolic execution when:

- input reaches a clearly identifiable success block;
- state space is controlled;
- external interactions can be modeled or stubbed;
- path explosion can be limited with find/avoid conditions.

Do not launch angr blindly on packed, event-driven, kernel, or heavily interacting programs. First reduce the problem with static analysis, hooks, and concrete execution.

## 7. Verification

A Crypto/Reverse solve should include:

- exact parsing of supplied values/files;
- recovered intermediate values with validation assertions;
- deterministic final decode/decrypt/path;
- a minimal script runnable from a clean directory;
- environment/dependency versions for Sage, Crypto libraries, emulator/hook tools;
- no embedded real competition flag in reusable knowledge.
