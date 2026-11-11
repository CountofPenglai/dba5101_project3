# Focused continuous-run validation

No full test suite was run after the user requested focused verification only.
The initial pre-change baseline was 52 tests. Feature verification uses targeted
CVaR, recovery, interruption, scheduler and entrypoint checks with fake HTTP and
temporary databases. The real saved history remained at 15,054 with one pending
request throughout implementation/review.

## Numerical and memory checks

- Weighted empirical CVaR agrees with the Rockafellar–Uryasev minimization formula
  across 40 discrete weighted distributions at four tail levels, with scaling and
  translation checks; boundary example gives 28 registrations.
- Sequential simulated UCB choices match the live policy on a traced small case,
  including the stage-to-continuation coefficient transition.
- One-million-row aggregate loading: 0.119 seconds, 6,562 bytes peak Python-traced
  allocation, SQLite cache set to 4 MiB. This does not measure total process RSS.
- 20,000 fake online pulls with real SQLite FULL commits and real log fsync:
  16.72 seconds excluding real network/pacing. Python-traced peak 73,122 bytes;
  retained allocation did not increase with pulls. See the adjacent JSON reports.
- Small isolated worker ran successfully. A 10,000-step rollout across 96 worlds
  and five candidates took 0.73 seconds locally; no real-budget forecast is inferred
  from fake HTTP throughput.

## Astra runtime review

The user requested a fresh Astra review restricted to runtime risks and CVaR
fidelity. The reviewer found no Critical issue and one Important regression:
Phase 3 had lost its Windows lock adapter when its old Phase 1 dependency was
removed. The shared driver lock now supports fcntl and the Windows msvcrt byte-lock
fallback. A focused regression first failed without fcntl, then passed after the
fix; the existing POSIX contention check also passed.

The reviewer checked fractional CVaR boundary mass, complete-mixture importance
weights, stationary latent worlds, phase accounting, independent validation and
ESS gates. A 100,000-draw check found mean importance weight 0.995054, max weight
1.999999708 and max posterior-coordinate mean discrepancy 3.9e-5. Actual worker
timeout and cancellation both terminated and reaped the worker (returncode -15).
No additional runtime blockers were identified in the reviewed paths.

Limits: no real Windows host test, no multiday process-RSS measurement, no real
server request during review, and no empirical proof of reward improvement or
global/distribution-free CVaR guarantees. These remain explicit model/testing
limits, not inferred guarantees.

## Final focused verification and authorized recovery

After the Windows fix, 33 focused tests passed. No full suite ran. The supplied
cloud helper is unchanged and notebook outputs are cleared. The user then
explicitly authorized resolving the single original pending request before push.
At 00:01 Singapore time on 12 November, that same UUID/counter/arm returned 21
registrations. Local/server totals both became 15,055 pulls and 365,500 sign-ups,
with no pending row. The previous 15,054 result rows are unchanged and SQLite
integrity_check returned ok. No fresh request UUID was created. See
`phase3/results/pending_recovery_2026-11-12.json`.

The credential was supplied only through hidden runtime input, was not written
to files/command arguments, and a repository-content scan found no matching value.
