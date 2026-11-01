# GP3 Bandit Framework Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. The user requested direct implementation with routine decisions delegated.

**Goal:** Persist real pull results, rebuild uniform/UCB models from history, and run bounded, paced online experiments with recovery and an append-only audit log.

**Architecture:** Keep the supplied `program/server_pull.py` unchanged. A standard-library Python package separates models, SQLite storage, paced transport, JSONL logging, and orchestration. One database is bound to one server/group and protected by a local driver lock.

**Tech Stack:** Python 3.9+, standard library (`sqlite3`, `unittest`, `argparse`); macOS/Linux file locking.

**Spec:** User requirements and the clarified contract below; original assignment in `doc/GP3 Multi-Armed Bandit Project.pdf`.

## Contract / Global Constraints

- `run_experiment(model, budget, *, online=False, db_path=..., username=None, password=None, ...)` is the shared Python entry point; CLI exposes the same choices.
- Offline mode fits all locally saved real observations and reports the next arm; it never contacts the server or manufactures rewards. Budget is an online completion cap and does not truncate offline training.
- Online budget counts successfully resolved pulls during this invocation, including recovery of a pending pull. Retries of the same request do not consume extra budget slots. Group cap is 1,000,000 pulls, 100 visitors each, arms 0..23.
- Uniform exploration selects the least-observed arm (lowest-ID tie break). UCB selects unobserved arms first, otherwise `mean(Reward/100) + sqrt(exploration * log(total_pulls) / arm_pulls)`, default exploration 2.0. Saved results are the source of truth; fit resets state before replay.
- SQLite commits each result immediately, deduplicates by pull index, rejects contradictory duplicates, and stores pending request identity before sending. Results and clearing pending are one transaction.
- Import existing real response dictionaries / JSONL without contacting the server. Bind their provenance explicitly to the assigned group and server. Never automatically import illustrative notebook outputs.
- Append a separate JSONL online log containing lifecycle, attempt, retry, and result events. Never log credentials or untrusted exception strings.
- At least 0.25 seconds between HTTP calls, including status calls; uncertain retries wait at least 1 second and reuse exactly the same UUID, arm, and counter. Retries are bounded; unresolved requests survive restart and are resolved before selecting another arm.
- Fail closed at the deadline (2026-11-15 23:59 Asia/Singapore) or server closure for new pulls. Permit recovery attempts of existing pending requests, subject to server behavior.
- All verification is offline using a fake transport; do not consume the group's experimental budget.
- README and code documentation are English. Preserve the starter and supplied client.

## Review Focus

- Crash after a server commit and before local commit: recover the same request and save once.
- Partial historical imports, duplicate/conflicting records, and mixing group/server identities.
- Offline mode with existing pending requests and online budget zero: no HTTP calls.
- Status/retry pacing, exhausted group budget, deadline, and server closure.
- Logs and databases must never contain passwords, including on error paths.

## Task 1: Models and durable storage

**Files:** `program/bandit/models.py`, `program/bandit/storage.py`, `program/tests/test_models_storage.py`.
**Interfaces:** `UniformModel`, `UCBModel(exploration=2.0)` expose `fit(results)`, `update(result)`, `select_arm()`, `summary()`. `HistoryStore(path)` exposes binding, append/import, ordered history, pending/complete, export and locking.
- [x] Write behavior tests for replay reset, uniform balance, UCB values/selection, validation, import deduplication, database identity and durable pending state.
- [x] Run tests and confirm failures caused by missing features.
- [x] Implement and run the model/storage test suite.

## Task 2: Paced online driver and audit log

**Files:** `program/bandit/client.py`, `program/bandit/audit.py`, `program/bandit/runner.py`, `program/bandit/__init__.py`, `program/tests/test_runner.py`.
**Interfaces:** Public `run_experiment` consumes a model name or instance, budget, mode, database and credentials. Return a JSON-serializable summary with learned counts, next arm, completed pulls and stop reason.
- [x] Write offline transport tests covering budgets, full-state replay, sequential request selection, pace, retries/restart, closed/deadline behavior, locking and redacted logs.
- [x] Confirm expected failures, implement the driver and append-only logging, then pass the whole suite.

## Task 3: CLI, documentation and final verification

**Files:** `program/bandit/__main__.py`, `program/tests/test_cli.py`, `README.md`, `.gitignore`.
- [x] Test default-offline run, import/export, validation and CLI summaries without networking.
- [x] Implement command-line access, English README with API examples, storage/recovery semantics, UCB formula and limitations.
- [x] Run the full unittest suite and documented offline smoke examples. Check Python 3.9 syntax and unchanged supplied client.
- [x] Obtain one independent code review, address important findings and rerun relevant/full tests.

## Execution Record

- User confirmed recommended offline behavior and delegated implementation details; added explicit online log requirement.
- Ruling: the supplied directory is not a Git repository. Work in place; skip Git/worktree/commit-specific helper scripts, retaining progress here.
- Pre-flight: runner consumes the model replay and storage pending/result APIs from Task 1; CLI consumes runner summary and storage import/export. No conflicting interfaces.
- Task 1: complete. Model/storage tests first failed for missing implementation; 11 tests now pass. Corrected synthetic fixtures whose cumulative rewards exceeded the visitor count and a hand-calculation typo; production validation remained intact.
- Task 2: complete. Fifteen new driver tests failed before implementation; 26 model/storage/runner tests then passed. Real helper code is exercised with HTTP I/O replaced by a deterministic fake server.
- Task 3: CLI and English README implemented. Five CLI tests failed before implementation; all 31 tests pass. Package files parse with Python 3.9 grammar. Supplied helper SHA-256 unchanged: 0ecc7e854015f021f7cb960dcaeff246830b0ede26d0de7154685c00b17fc6ec.

- Final review: independent reviewer confirmed a deadline-crossing-during-pacing defect. Added a regression test and observed RED (one pull sent), then implemented a pre-transmission guard and known-unsent cancellation; the full suite is GREEN (32/32). No deferred minor findings.
- Final: Ruling: retain recovery of previously durable pending requests after deadline, because a prior interrupted transmission cannot prove whether the server committed. Cost: availability of such recovery depends on the server.
- Final: Ruling: local locking covers one resolved database on one machine; cross-device coordination remains the group's responsibility. Cost: separate drivers can still conflict or share the rate limit.
- Final: Ruling: imported records require explicit group/server binding but cannot cryptographically prove provenance. Cost: importing another group's data with incorrect labels can bias learning.
- Final: Ruling: advanced policy performance and live-server idempotency are not claimed by these local tests. Cost: actual environment behavior remains unverified until the user's first intentional online run.
- Final checks: offline Python API/import/export smoke passed; supplied helper checksum unchanged; no real server calls made. This non-Git workspace was edited in place with no branch or commit operations.
