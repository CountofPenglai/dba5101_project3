# Optional finite-horizon UCB tuning

## Objective and theory

Let D be the current sufficient statistics, R the remaining group allowance up to
the configured absolute target, and H=min(200000,R). A stage chooses a UCB bonus
multiplier c. Arms are still chosen and updated after **every** observed pull.
The restricted Bayesian Bellman objective is

`V_R(D) = max_c E[G_H(c) + V_(R-H)(D'_c) | D]`.

This values both next-stage registrations and the information's benefit to all
later pulls, without counting the first stage twice. The implementation uses a
one-stage **rollout approximation**: candidate c for H pulls, followed by the
current multiplier for R-H pulls, continuing to learn after each simulated result.
It does not simulate future parameter retuning or solve the complete Bellman tree.
At the next real checkpoint the decision is recomputed from real data. The planning
horizon is remaining group/absolute-target budget, not the optional per-invocation
pause limit. The deadline still gates actual new HTTP calls; planning assumes the
chosen horizon can be completed before it.

Sources: [Bayesian finite-horizon bandits](https://www.jmlr.org/papers/v24/22-1181.html),
[rollout and approximate dynamic programming](https://arxiv.org/abs/2212.07998).

For each arm, `p_i ~ Beta(1+signups_i, 1+100*pulls_i-signups_i)`. Each simulated
world draws latent p once. The policy sees only sampled Binomial(100,p_i) rewards.
Stationarity and independent visitors are assumptions, not facts established by
the simulator. There is no resampling of the true environment at every pull.
The simulated UCB formula, tie break and coefficient conversion match the live
model: `mean + sqrt(exploration * log(total_pulls) / arm_pulls)`, with
`exploration=round(2*c*c,12)`.

## Loss, CVaR and validation

Full-horizon pseudo-regret, in registrations, is
`L_R = 100 * sum_t (max_i p_i - p_chosen_t)`.
It measures both exploratory opportunity cost and continued exploitation of a
mistaken leader. Expected total reward maximization and expected pseudo-regret
minimization are equivalent under these posterior worlds. We do **not** add a
second arbitrary penalty for the same wrong-arm losses.

For confidence level alpha (default .95), the upper-tail loss metric is

`CVaR_alpha(L) = min_eta [eta + E[max(L-eta,0)] / (1-alpha)]`.

For weighted empirical worlds, sort losses descending, accumulate normalized
probability mass to exactly `1-alpha`, and use only the required fraction of the
boundary atom. Divide this weighted tail sum by `1-alpha`. Simply averaging all
losses above a percentile would be wrong with ties or unequal weights. The tests
compare this implementation against the minimization formula on discrete weighted
distributions, including partial boundary mass, zero weights, translation and
positive scaling. Invalid inputs raise rather than producing NaN.

This assesses **risk of cumulative decision regret**, not CVaR of an individual
arm's per-pull revenue. See [CVaR-Regret Bounds for Multi-armed Bandits](https://proceedings.mlr.press/v189/tan23a.html).

Training worlds rank candidate multipliers. Only one preselected candidate is
checked against the baseline in fresh validation worlds with fresh observation
noise. A switch requires all of:

- Full-horizon mean regret difference + 2.58 Monte Carlo SE < -minimum gain.
- Stage mean regret difference + 2.58 SE <= stage loss allowance (default 0).
- CVaR difference + 2.58 paired-bootstrap SE <= tail loss allowance (default 0).
- Overall importance-weight ESS >=32 and both tails have ESS >=4.

These are **approximate Monte Carlo safeguards**, not distribution-free confidence
bounds or a guarantee that real rewards improve. The 96-resample bootstrap can
still be unreliable in very rare tails. The baseline is retained on insufficient
support, uncertain improvement, invalid worker output, missing NumPy, timeout or
worker failure. The baseline itself is not certified safe by being retained.

Every replan applies relative CVaR screening independently. This is **not** a
time-consistent global CVaR constraint. Strict multistage risk consistency would
require nested risk measures or an augmented risk-budget state, beyond this
implementation: [risk-averse dynamic programming](https://optimization-online.org/wp-content/uploads/2009/12/2497.pdf).
Published UCB/CVaR regret bounds do not automatically apply to our scaled/tuned UCB.

## Rare scenarios and importance weights

Plain posterior draws can miss the event that the current leader is wrong. We
therefore sample a defensive proposal: half the original joint posterior, half
an equal mixture of 23 proposals, each tilting one challenger's Beta distribution
toward the leader. Other coordinates retain their original posterior. Each draw
receives the **complete mixture** density ratio posterior/proposal, bounded by 2.
Weights are normalized for empirical expectations and CVaR; normalization introduces
finite-sample bias. This is not an unweighted stress test and does not fabricate
extra probability for rare scenarios. Full-support sampling, density ratios and
effective tail sample size matter as much as the number of simulations.

The report includes conditional full regret when the current empirical leader is
not truly best, and the weighted probability of that event. They are diagnostics,
not an additional objective counted twice.

## Operation

- Enable `AUTO_TUNE=True` in `phase3/config.py` or the notebook, or pass `--auto-tune`.
- Initially evaluate once all arms have data; then every 200000 newly saved pulls.
- The SQLite `tuning_decisions` journal and `metadata.tuning_state` commit together.
  Saved `next_at` and selected multiplier survive restart. A changed tuning config
  triggers a new evaluation; disabled tuning uses the configured fixed multiplier.
- Resolve pending requests before tuning. Persist the decision before sending a
  request under the new coefficient. Each result keeps its actual parameters.
- A disposable worker receives only aggregate counts/settings via a private
  temporary directory. It gets no account, password, database path or credential
  environment. No HTTP is used. Arrays scale with worlds*candidates*24, not horizon.
- Default worker timeout: 600 seconds. It is terminated and reaped on timeout or
  stop. Finished/failed decisions advance the schedule; interrupted evaluations
  leave no partial decision and can be retried on restart.
- Offline `run` only fits/recommends. For an explicit local simulation preview:

```bash
cd program
python3 -m bandit tune --multiplier 0.05 --remaining 984946 --seconds 600
```

The preview never changes history or the active tuning schedule. The remaining
argument above is illustrative; omit it to derive the cap from the local maximum
pull index. The next online run uses server status for the authoritative allowance.

Fixed-policy runs need only the Python standard library. Tuning requires NumPy in
the interpreter used to launch the driver (`python3 -m pip install numpy`).
