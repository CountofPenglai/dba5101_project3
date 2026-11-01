# GP3 Run Notebook Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. The user already delegated implementation details and requested direct implementation.

**Goal:** Add an operational notebook with centralized settings, private account input, one run cell, and local result/statistics/log inspection.

**Architecture:** A new `program/GP3 Run.ipynb` calls the existing public API. It introduces no runtime package dependencies beyond the notebook environment and no changes to bandit policy or online transport behavior. View cells query SQLite read-only and stream a bounded tail of the JSONL log.

**Tech Stack:** Python 3.9+, standard library, IPython display provided by Jupyter.

**Spec:** This document captures the user's notebook request and the existing framework's offline contract.

## Global Constraints

- First code cell holds model name, UCB exploration, budget, ONLINE=False, username, database/log paths, pacing/retry parameters and display row limits. Passwords never appear in configuration or saved outputs.
- Resolve relative paths against the program directory whether the kernel starts in program/, project3/, or the parent 5101/ folder.
- Prompt for credentials only on an intentional online run with positive budget. Clear the local password reference in finally. Reset the previous run summary before running; show sanitized errors and preserve the ability to inspect saved data after interruption.
- Viewing cells never call the live API, regardless of the ONLINE setting. Display local identity/pending state, bounded recent results, all 24 arms (pulls, visitors, sign-ups, conversion rate, allocation share, optional UCB index), and recent log events.
- No fabricated observations are saved into project data. Ship the notebook with empty outputs and execution counts. Document that rerunning the online execution cell can spend another budget and HTML export must not execute cells.
- Preserve the supplied starter and client. Work in place; this directory is not a Git repository.

## Review Focus

- Run All in default offline mode: no credentials requested and no HTTP.
- Online run: settings propagate, secrets stay out of output, and reruns do not display stale summaries.
- Views refreshed after the database changes: correct counts and no extra pulls even when ONLINE=True.
- Empty history, partial history, pending recovery and large logs: explicit, bounded display.
- Invalid settings fail before prompting or networking; errors/interruption leave saved data inspectable.

## Task 1: Notebook behavior tests

**Files:** `program/tests/test_notebook.py`.
- [x] Execute notebook cells in a temporary directory with real stored fixtures and a fake HTTP boundary; test offline defaults, online settings, credential handling, refreshed statistics, paths and failure behavior.
- [x] Run tests and observe missing-notebook failures.

## Task 2: Operational notebook and README

**Files:** `program/GP3 Run.ipynb`, `README.md`.
- [x] Create the configuration, setup, run, local snapshot, statistics, results and log display cells using existing APIs and SQLite read-only queries.
- [x] Document the notebook workflow and pass the notebook and full test suites.

## Task 3: Verify and review

- [x] Execute default and populated-history notebook smoke runs without live calls; validate notebook structure and clean shipped outputs.
- [x] Perform independent read-only review; fix material findings with regression coverage.

## Execution Record

- Pre-flight: notebook consumes `run_experiment`, `UniformModel`, `UCBModel`, and the existing SQLite result/metadata/pending schema; no framework interface changes are planned.

- Tasks 1 and 2 complete: nine missing-notebook failures observed before implementation; all 41 tests now pass. Notebook tests execute the actual cells and existing runner with only HTTP and display boundaries replaced. README updated.

- Task 3 complete: empty and populated-history scenarios executed all notebook cells with real IPython display, producing five HTML tables each; all requests were forbidden and data stayed in temporary directories. Notebook format/clean outputs/Python 3.9 syntax checked.
- Independent review found one P2: full run-settings validation blocked local views after an invalid run. Two regression tests reproduced the failure; split execution/path/view validation and passed the complete 43-test suite. No deferred material findings.
- Verification note: an intermediate suite invocation from project3/ failed to import program modules; rerunning the documented command from program/ passed. This was a working-directory error, not a code failure.
- Reviewer did not assess rendering/live behavior. Parent validated actual IPython rich outputs; live-server behavior remains untested and no experimental budget was consumed.
