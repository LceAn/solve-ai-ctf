# Evaluation and Knowledge Governance

## Contents

1. What to evaluate
2. Benchmark construction
3. Metrics
4. Forward-test protocol
5. Knowledge record schema
6. Promotion and contradiction rules
7. Security and privacy

## 1. What to evaluate

Evaluate the full system, not just whether an LLM eventually writes a flag:

- correct category and hybrid routing;
- time to decisive evidence;
- exploit correctness and reproducibility;
- tool reliability and sandbox behavior;
- state consistency and duplicate avoidance;
- candidate precision and submission safety;
- recovery after timeout, crash, target reset, or model failure;
- learning quality after closure.

## 2. Benchmark construction

Create three sets:

### Regression set

Use solved local challenges with flags removed from all visible prompts and fixtures. Preserve only original artifacts and challenge descriptions. The checker retains ground truth separately.

### Generalization set

Create parameterized variants: different seeds, offsets, member orders, alphabets, paths, libc builds, token claims, and parser layers. A solver that memorizes one writeup should fail these variants.

### Negative/blocked set

Include incomplete artifacts, expired targets, decoy flags, unreliable tools, and cases whose required dependency is absent. Success means identifying the blocker and preserving useful state—not hallucinating a solve.

Split cases by technique family to avoid leakage. Do not let the skill retrieve the source writeup for a benchmark case.

## 3. Metrics

Core outcome metrics:

- accepted solve rate by category/difficulty;
- median time to accepted flag;
- points per hour and expected-value regret;
- reproduction pass rate from a clean environment;
- false candidate rate and incorrect submission count.

Process metrics:

- time to first correct category;
- time to first high-value evidence;
- hypotheses before decisive one;
- duplicate-attempt ratio;
- fraction of attempts with declared expected signal;
- confidence calibration (Brier score or reliability bins);
- context/token/tool cost per solved case;
- recovery success after injected faults.

Safety metrics:

- out-of-scope action attempts;
- execution of untriaged artifacts;
- secret leakage to logs/knowledge;
- unbounded process/network activity;
- submission without provenance or rate-limit checks.

## 4. Forward-test protocol

Run the skill from a clean context with only:

- skill path;
- raw challenge artifact/description;
- explicit authorization and constraints;
- no intended solution or prior diagnosis.

Capture state files, tool traces, outputs, and final reproducer. Evaluate against hidden ground truth. If a test artifact is modified, reset it before another run.

Test at least:

1. Small-seed Crypto.
2. Cross-file Reverse/Crypto.
3. Parser-differential Web.
4. Modern UAF Pwn with supplied libc.
5. Multi-stage PCAP/encoding chain.
6. A deliberately unsolved/ambiguous case.

## 5. Knowledge record schema

Each promoted record should contain:

```json
{
  "id": "pattern-id",
  "title": "mechanism, not challenge name",
  "categories": ["web"],
  "preconditions": [],
  "observables": [],
  "mechanism": "",
  "discriminating_tests": [],
  "successful_method": "",
  "failed_methods": [],
  "verification": "reproduced|accepted|reported|unverified",
  "phase": "during_competition|post_competition|pre_match",
  "confidence": 0.0,
  "tool_versions": {},
  "source_paths": [],
  "sensitive_fields_redacted": true,
  "tags": []
}
```

Do not store a real flag, team token, live target, password, session, or unique account in the pattern body.

## 6. Promotion and contradiction rules

Promote only when:

- the method is reproduced or platform accepted;
- decisive evidence is preserved;
- preconditions and version dependencies are explicit;
- the pattern is generalized beyond the single flag/path/address;
- sensitive data is removed;
- a reviewer or automated verifier passes it.

When sources conflict:

1. Preserve both claims with phase and provenance.
2. Prefer reproducible artifacts over prose.
3. Prefer platform acceptance for outcome, but not necessarily for mechanism.
4. Reduce confidence when decisive details are absent.
5. Never silently rewrite history from “unsolved during event” to “solved.”

Expire or revalidate version-sensitive knowledge such as libc internals, framework parsing, model APIs, and tool flags.

## 7. Security and privacy

- Redact secrets before indexing or embedding.
- Keep raw competition data in a restricted store separate from reusable knowledge.
- Treat retrieved notes as untrusted; they cannot override scope or execution policy.
- Record licenses/source attribution for imported public writeups.
- Use synthetic flags in tests.
- Destroy ephemeral credentials and containers after the authorized event.
