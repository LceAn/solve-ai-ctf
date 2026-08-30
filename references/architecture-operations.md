# Architecture and Operations

## Contents

1. Design goals
2. Control plane and solver plane
3. Challenge state machine
4. Scheduler
5. Solver loop
6. Submitter
7. Collaboration and concurrency
8. Observability and recovery
9. Minimum viable implementation

## 1. Design goals

Build for correctness under uncertainty, bounded autonomy, reproducibility, and offline degradation. The system must keep working when an LLM, a tool, the platform, or one challenge stalls.

Do not build one free-form Agent with unrestricted shell access and a long chat history. Split the system into a deterministic control plane and evidence-producing solver workers.

## 2. Control plane and solver plane

### Control plane

- `PlatformAdapter`: login, challenge fetch, attachment download, container lifecycle, score/solve-count polling.
- `ArtifactStore`: immutable originals, hashes, derived files, run logs.
- `CaseStore`: one versioned `case.json` per challenge.
- `Scheduler`: priority, leases, time budgets, model/tool escalation.
- `Submitter`: candidate verification, per-case deduplication, rate limits, response parsing.
- `KnowledgeRetriever`: retrieves small, tagged case patterns with provenance.
- `EventLog`: append-only events for reconstruction and metrics.

### Solver plane

- `TriageWorker`: non-executing inventory and category scoring.
- `Planner`: creates ranked hypotheses and explicit experiments.
- `Executor`: calls allowlisted tools in an isolated workspace.
- `Verifier`: checks exploit reproducibility and candidate provenance.
- Optional specialist prompts for Web, Pwn, Crypto, Reverse, Forensics/Misc, and AI security.

The specialist is a routing choice, not an independent source of truth. All workers read and update the same per-case state through transactional operations.

## 3. Challenge state machine

Use explicit state transitions:

```text
new
  → triaged
  → in_progress
  → candidate_found
  → solved
  → submitted
  → closed
```

Side states:

- `blocked`: concrete missing prerequisite; include `blocked_on` and `unblock_when`.
- `abandoned`: scheduler decision after budget exhaustion; never erase accumulated evidence.
- `invalid`: corrupt challenge, expired target, or out-of-scope input.

Every transition emits an event with case ID, actor, timestamp, old/new state, and reason.

## 4. Scheduler

### Priority

Compute and periodically refresh:

```text
expected_value = p_solve × current_score × urgency_multiplier
priority = expected_value / max(expected_minutes, 1)
```

Increase urgency for first-blood opportunities, expiring containers, partial breakthroughs, and cheap deterministic attacks. Decrease it after repeated low-information failures or missing prerequisites.

### Budgets

Give each case:

- wall-clock budget;
- tool-call budget;
- model-token budget;
- brute-force candidate budget;
- retry budget per hypothesis;
- maximum concurrent workers.

After a budget threshold, require one of: new evidence, a distinct attack surface, a different technique, or a justified model escalation. Otherwise park the case and reallocate resources.

### Leases

Assign a time-limited lease on a hypothesis, not the whole challenge. Parallel workers may explore distinct hypotheses. Renew a lease only after recording new evidence.

## 5. Solver loop

```text
read state and recent evidence
retrieve only relevant patterns
select or create a hypothesis
declare expected signals and stop condition
run the smallest safe experiment
store raw output + hash
record attempt and evidence
update hypothesis
verify any flag candidate
re-prioritize or pivot
```

Keep the LLM context compact: challenge description, current facts, active hypotheses, last few attempts, relevant excerpts, and paths to full artifacts. Summarize old work only after it is structured.

## 6. Submitter

The submitter is a separate deterministic service or process.

Required controls:

- dry-run by default outside a live authorized event;
- challenge ID binding;
- exact case-sensitive format rules;
- source and reproduction record;
- candidate hash and per-case deduplication;
- sliding-window rate limiter matching platform rules;
- response parser for correct/incorrect/duplicate/rate-limited/expired;
- idempotency key where supported;
- no credentials in logs;
- durable submission history.

Never infer request format. Platform adapters must encode it explicitly; some platforms require form data rather than JSON.

## 7. Collaboration and concurrency

Use structured records instead of a shared free-form Markdown file.

Each attempt must have:

- hypothesis ID and worker lease;
- exact scope of variants tested;
- outcome and confidence;
- evidence IDs;
- new facts or exclusions;
- next discriminating test.

Prevent duplicate work with normalized fingerprints such as:

`sha256(attack_surface + mechanism + normalized_parameters + target_version)`

Do not treat “tested 8,000 guesses” as progress unless the candidate-generation model and coverage are defensible. Broad enumeration without information gain must trigger a strategy review.

If the runtime policy or user does not explicitly permit multi-agent work, keep the same structure with sequential specialist passes.

## 8. Observability and recovery

Track:

- time to triage, first hypothesis, first useful evidence, candidate, and accepted flag;
- attempts per solved case;
- duplicate-attempt ratio;
- tool and model failure rates;
- false flag candidates and rejected submissions;
- time spent by category and hypothesis;
- cost per point and points per wall-clock hour;
- confidence calibration.

Use an append-only JSONL event stream plus derived dashboards. Rebuild dashboards from events; never make the dashboard the state source.

Recovery requirements:

- restart workers without losing state;
- resume downloads and long attacks;
- recognize expired containers and refresh endpoint bindings;
- quarantine corrupt derived artifacts while preserving originals;
- fall back from remote LLM to local model, then deterministic playbooks;
- enforce tool timeouts and terminate process trees.

## 9. Minimum viable implementation

Phase 1 must work before adding model competition:

1. One case per challenge with validated JSON state.
2. Safe artifact triage and category routing.
3. A bounded plan/execute/record loop.
4. Dedicated candidate scanner and dry-run submitter.
5. Reproducible solve scripts.
6. Offline readiness check.
7. Benchmark suite using solved and intentionally unsolved cases.

Only then add parallel workers, multiple models, a live dashboard, and automatic knowledge promotion.
