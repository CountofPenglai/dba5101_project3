# Continuous runs and finite-horizon UCB tuning

The user approved full-remaining-budget planning, a 200,000-pull decision interval,
stage performance safeguards, and explicit wrong-arm loss assessment. Implement in
the existing checkout, preserving all uncommitted pacing changes and real data.
Online execution remains paused. No real HTTP calls are part of verification.

## Runtime contract

- `budget=None` means all remaining server allowance; integers cap additional
  completed pulls in this invocation. An optional absolute `target_total` also caps
  the server counter. The group-wide limit remains 1,000,000, not another million.
- Offline remains the default. Phase 3, the CLI and the notebook share one runner.
- Model state is 24 counts and signup totals. Load it with SQL aggregation; never
  retain all responses. Views and terminal progress are bounded.
- First SIGINT/SIGTERM requests a graceful stop after saving any response already
  in flight. A second interrupt can force exit; durable pending identity survives.
- Uncertain requests retain their original arm, UUID, counter and model parameters.
  Infinite retries use explicit `max_retries=None` (the continuous entry default; the API defaults to 2), paced with bounded exponential
  backoff. Definite rejections, local storage failures and mismatched history stop.
- Keep the supplied cloud helper unchanged, sequential requests, >=0.25 s spacing,
  >=1 s uncertain retry cooldown, FULL SQLite durability and secret-free logs.

## Tuning approximation

Beta(1+signups, 1+100*pulls-signups) independent stationary posteriors. At a tuning
boundary compare positive UCB multipliers, including the current one. Simulate
each pull exactly; candidate multiplier for H=min(interval, remaining), then the
current multiplier as a fixed continuation policy through the remaining horizon.
This is a one-block rollout approximation to the Bayesian Bellman equation, not a
solution of the full adaptive decision tree. No clairvoyant actions or reuse of
latent simulated rates by the policy. The same latent worlds compare candidates;
an independent validation stream checks any switch.

Rank by expected full-horizon pseudo-regret (in signups). Require validated
improvement, a stage-regret difference upper confidence estimate <= stage loss
allowance (default 0), and full-horizon CVaR no worse than baseline plus an explicit
allowance (default 0). Tail level defaults to 0.95 because finite simulation cannot
reliably estimate 99.999% tails. Report probability and conditional regret when
the current leader is wrong. Use a defensive mixture proposal tilted toward
challenger-best worlds, exact density importance weights, effective sample sizes,
and a fail-closed validation gate. Do not confuse conditional scenario diagnostics
with a model-free guarantee. CVaR is a per-replan safeguard, not a time-consistent
global risk guarantee. Risk budgets and model assumptions are documented.

Run tuning in a disposable subprocess with aggregate-only JSON input, no account
or password environment, bounded simulation arrays and a wall-clock limit. On
timeout/failure retain the baseline. On manual stop kill/reap the worker and keep
the run paused. Persist decisions and next due count atomically; restart restores
the selected coefficient and schedule only for matching configuration. Disabled
tuning uses the explicitly configured fixed coefficient. Never tune with pending
HTTP state. Offline run only trains/recommends; a separate offline tuning preview
is available. Log actual per-pull parameters and replay those parameters.

## Verification

Fake-server tests cover recovery, caps, stop during transmission/retry/tuning,
deadline, missing history, disabled tuning and scheduling across restart. Tests
cover simulation policy parity, horizon decomposition, validation rejection and
worker cleanup. A synthetic million-row SQLite check measures bounded load/view
memory; a long fake run checks that per-pull objects do not accumulate. Astra
reviews runtime risks after implementation, as requested by the user.
