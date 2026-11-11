# Request pacing optimization

> Implementation: native execution with tests first and one independent final review.

**Goal:** Improve sequential online throughput while retaining the project's request spacing, recovery, budget, deadline, and durability rules.

**Specification:** The project handout, page 3, requires one sequential group driver, at least 0.25 seconds between calls, and at most five requests per second per group. Interpret spacing as actual request start to start. Never overlap requests or catch up after a slow request. The user requested optimization, not another live-pull stage; measurements use status only.

**Architecture:** Keep the supplied HTTP helper, database, model, and logging intact. Change only the pacing scheduler to credit elapsed network/local work toward the minimum interval. Keep an initial delay on each client, recheck the monotonic clock after waking, preserve the one-second uncertain-request cooldown, and check the deadline after waiting. Serialize calls inside one client as well as preserving the existing driver lock.

**Constraints:** Python 3.9+, standard library; interval >= 0.25; no new pulls for benchmarking; TLS verification enabled; save every outcome and pending identity. Preserve the existing 5,000 real rows and all previous workspace changes.

## Task 1: Pace by actual starts

- [x] Add failing tests for fast/slow responses, local processing, no catch-up bursts, early wakeups, failure cooldown, and serial calls.
- [x] Change `program/bandit/client.py`; keep the public interface and supplied helper unchanged.
- [x] Run the complete offline suite and `phase3/check.py`.

## Task 2: Measure and document

- [x] Analyze existing event timestamps, labeling inferred timing separately from measurements.
- [x] Run a bounded status-only before/after benchmark if credentials are supplied; confirm server counters stay at 5,000 and 119,597.
- [x] Save benchmark evidence and update the English README with spacing semantics, practical throughput, and deadline assumptions.
- [x] Review the final change independently; address important findings with regression tests.

## Review focus

- A long/failed request must not produce a catch-up burst.
- Early sleep returns must never shorten minimum spacing.
- An uncertain pull retains its identity and waits at least one second before retrying.
- A deadline reached during a pacing wait cancels only an unsent fresh request.
- Benchmarking must not issue POST requests or mutate the real database/log.

## Decisions and verification

- Work in the existing checkout so the user's saved 5,000-pull state remains the active data source; do not reset, stash, commit, or push their existing changes.
- No new public model or transport settings are introduced; the UCB multiplier remains 0.05.

- Verification: seven initial pacing tests failed against the old scheduler; the precreated-client regression subsequently failed with a 0.05-second gap before the acquisition guard was added. All 52 tests now pass, as do phase3/check.py and Python 3.9 syntax checks.
- Live measurement: 120 status-only calls, unchanged counters (5,000 pulls / 119,597 sign-ups), minimum spacing 0.250250 seconds, at most four calls in any measured closed one-second window. Full measurements are in phase3/results/pacing_benchmark.json.
- Security verification: scanned repository files and non-credential benchmark artifacts against the supplied credential without displaying it; no matches. The permission-restricted temporary credential was deleted after measurement.
- Independent review: no Critical or Important findings; reviewer independently reran 52 tests and checked measurement/deadline arithmetic. The checklist completion note was addressed by this planned finalization.
- Review scope: actual optimized live-pull throughput remains unmeasured, so forecasts are conditional. Earlier live-stage data remains intact. The supported operating contract remains one sequential group driver; using the helper separately or outside that lifecycle can bypass pacing and must not be combined with this driver.
