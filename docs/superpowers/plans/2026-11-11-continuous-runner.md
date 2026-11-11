# Continuous Runner Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task.

**Goal:** Support durable bounded-memory continuous runs and optional horizon-aware tuning.
**Architecture:** SQL summaries and durable scheduling surround one sequential runner;
an isolated simulation worker evaluates UCB coefficients without touching real data.
**Tech Stack:** Python 3.9+, SQLite, standard library; optional NumPy for tuning.
**Spec:** docs/superpowers/specs/2026-11-11-continuous-runner.md

## Global Constraints

- Do not resume online pulls or alter the live database during development.
- Preserve supplied server_pull.py and existing uncommitted work.
- One million is the group-wide cap; offline default; no credentials in artifacts.
- Use temporary databases/fake HTTP for all tests.

## Review Focus

- Stop after server commit but before local save: retain exactly-once recovery.
- Tuner timeout/interrupt: terminate and reap subprocess, never change parameters partially.
- Restart at tuning boundary: no lost schedule or duplicate parameter change.
- Partial log lines, huge histories, repeated transient failures: bounded memory.
- User caps and mismatched server counters: no unintended extra pulls.

### Task 1: Bounded storage and stop control
- [x] Add failing tests for aggregate loading, durable tuning state, log tail and signal control.
- [x] Implement `fit_aggregates`, `HistoryStore.aggregate`, tuning journal, bounded log tail,
  and a stop controller without modifying cloud helper behavior.
- [x] Run storage/model/runtime tests.

### Task 2: Local tuning and worker lifecycle
- [x] Add failing tests for exact UCB rollout, horizon accounting, selection safeguards,
  reproducibility, timeout and stop cleanup.
- [x] Implement `TuningConfig`, local `evaluate`, `evaluate_isolated` and worker entry.
- [x] Run tuning tests and benchmark realistic horizons.

### Task 3: Continuous runner integration
- [x] Add failing fake-server tests for None budget, absolute cap, graceful stop,
  infinite uncertain recovery, strict history matching, durable optional tuning.
- [x] Integrate runner with persisted scheduling, progress callbacks and stop control.
- [x] Run only targeted runtime/recovery tests (user explicitly excludes the full suite).

### Task 4: Entrypoints and documentation
- [x] Add CLI/notebook/Phase 3 tests for omitted limits and configurable tuning.
- [x] Update entrypoints, bounded views, mixed-coefficient replay, English README.
- [x] Run focused CVaR, interruption, restart and bounded-memory checks; no full suite.
- [x] Request Astra runtime-risk review, fix substantive findings with regression tests.

## Execution ledger

- Baseline: 52 tests pass with `cd program && python3 -m unittest discover -s tests -q`.
- Work in place: user requested changes to the current entry, and real recovery state
  plus existing edits must stay intact. No branch switching, commits or network runs.
- User approved the design and implementation; proceed without another approval cycle.

- User steering: do not run the full suite. Prioritize faithful CVaR and runtime crash risks; Astra review must cover these.

- Implemented Tasks 1–4. Focused verification: 31 tests passed; full suite intentionally not run.
- Synthetic million-row load: 0.119s, Python peak 6,562 bytes. 20k fake pulls with real FULL commits/fsync: Python peak 73,122 bytes, no growing history retained.
- Astra read-only runtime/CVaR review in progress. No real HTTP requests or real DB writes so far.

- Astra review complete: one Important Windows-lock regression fixed with RED→GREEN fallback and POSIX contention checks; no further runtime blockers. See docs/performance/2026-11-11-continuous-validation.md.
- User authorized one pending-request recovery and direct commit/push after completion. No batch run is authorized by this final step.

- Final targeted verification: 33 tests PASS. Original pending request recovered alone: saved/server 15,055 pulls, 365,500 sign-ups, zero pending; original 15,054 rows unchanged. No fresh request UUID or batch run. Credential-content scan clean.
