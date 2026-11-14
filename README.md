# GP3: Multi-Armed Bandit Experiment Framework

## Final results: all 1,000,000 pulls

The live experiment is complete. All **1,000,000 pulls** were used, sending **100 million visitors** to the 24 arms and producing **24,449,708 sign-ups**, a conversion rate of **24.45%**. The last pull was saved on 14 November at 21:24 Singapore time, about 26.5 hours before pulls closed.

- **Verified:** pull indices 0 to 999,999 are all saved with no gaps and no pending request. The server's running total at the last pull (24,449,708) equals the sum of the saved rewards.
- **Best arm:** arm 21, at 24.45% (95% interval 24.45% to 24.46%) over 998,794 pulls. Its posterior chance of being the best arm is above 99.99%.
- **Cost of learning:** taking each arm's estimated rate as its true rate, always showing arm 21 would have earned about 24,453,693 sign-ups. Our total is **3,985 lower (0.016%)**. Of that, 2,108 was lost in the 240-pull pilot and 1,877 in the 999,760 pulls after it.
- **Method:** UCB ×0.05 (`exploration = 0.005`) from the pilot to pull 816,055. The fifth tuning check then switched to **UCB ×0.02** (`exploration = 0.0008`) for the last 183,945 pulls (see below).

### Results by stage

| Stage | Pulls | Policy | Sign-ups | Conversion | Share to arm 21 | Loss vs arm 21* |
|---|---|---|---:|---:|---:|---:|
| Pilot | 0 to 239 | Uniform, 10 per arm | 3,746 | 15.61% | 4.2% | 2,108 |
| Stage 1 | 240 to 1,199 | UCB ×0.05, fixed | 23,101 | 24.06% | 71.8% | 470 |
| Stage 2 | 1,200 to 16,054 | UCB ×0.05, fixed | 363,235 | 24.45% | 98.0% | 571 |
| Stage 3.1 | 16,055 to 216,054 | UCB ×0.05, kept by check 1 | 4,890,143 | 24.45% | 99.85% | 595 |
| Stage 3.2 | 216,055 to 416,054 | UCB ×0.05, kept by check 2 | 4,891,340 | 24.46% | 99.96% | 179 |
| Stage 3.3 | 416,055 to 616,054 | UCB ×0.05, kept by check 3 | 4,891,289 | 24.46% | >99.99% | 27 |
| Stage 3.4 | 616,055 to 816,054 | UCB ×0.05, kept by check 4 | 4,889,672 | 24.45% | 99.99% | 36 |
| Stage 3.5 | 816,055 to 999,999 | UCB ×0.02, set by check 5 | 4,497,182 | 24.45% | 100% | 0 |
| **All** | **1,000,000** | | **24,449,708** | **24.45%** | **99.88%** | **3,985** |

\*Sign-ups lost against always pulling arm 21, using each arm's estimated rate as its true rate.

### How the allocation evolved

- **Arm 21 took over quickly.** It led the pilot at 25.5% and received 72% of stage 1, 98% of stage 2 and over 99.8% of every later stage.
- **Two runners-up got most of the exploration.** Arm 12 ended at 23.30% (22.93% to 23.68%) over 496 pulls, and arm 0 at 22.85% (22.35% to 23.37%) over 261. Arm 12's gap to arm 21 is about 6 standard errors.
- **Exploration was front-loaded.** After the pilot, 976 pulls went to arms other than 21: 573 before pull 16,055 (3.6% of those pulls) and 403 after it (0.04%).
- **12 arms were never pulled again after the pilot.** These are the arms with pilot rates of 16.2% or lower. Arm 9 returned at pull 7,053, and arms 18 and 14 at pulls 90,433 and 199,066. These fit the stage 1 forecasts of about 6,600 for arm 9 and 85,000 to 900,000 for arms 18 and 14.
- **Pull counts follow the UCB rule.** UCB returns to a runner-up only while its bonus 0.05 × √(2 ln t / n) is bigger than its gap to the leader, so each runner-up settles near n ≈ 2(0.05)² ln t / gap². At pull 816,055, the last pull under ×0.05, that predicts 515 pulls for arm 12 (actual 496) and 266 for arm 0 (actual 261).

### Conversion and stability

- **Cumulative conversion** rose from 15.61% after the pilot to 22.37% at 1,200 pulls and 24.30% at 16,055, then settled at 24.45%.
- **No drift.** Arm 21's rate in 20 blocks of 50,000 pulls ranged from 24.42% to 24.50%. That is consistent with a constant rate (χ² = 23.4 on 19 df, p = 0.22). Per-pull variance is 0.998 times binomial.

### Tuning checks

Each check simulated every multiplier for the next stage, then the current one for the rest of the budget, on 96 posterior worlds. It tested the best alternative on 384 fresh worlds before switching.

| Check | At pull | Pulls left | Expected regret of ×0.05 (± SE) | Best alternative | Decision | Time taken |
|---|---:|---:|---:|---|---|---:|
| 1 | 16,055 | 983,945 | 1,018 ± 39 | ×0.03: 1,003 | Kept ×0.05 | 2 m 29 s |
| 2 | 216,055 | 783,945 | 315 ± 17 | ×0.03: 336 | Kept ×0.05 | 2 m 05 s |
| 3 | 416,055 | 583,945 | 182 ± 10 | ×0.02: 185 | Kept ×0.05 | 1 m 31 s |
| 4 | 616,055 | 383,945 | 142 ± 11 | ×0.02: 143 | Kept ×0.05 | 58 s |
| 5 | 816,055 | 183,945 | 44 ± 3.5 | ×0.02: 0 | **Switched to ×0.02** | 1 m 08 s |

- **Checks 1 to 4:** no alternative was clearly better than ×0.05, so it stayed. Only check 1 had a lower score: ×0.03, by 14 sign-ups against a standard error of 39. ×0.075 and ×0.10 would have cost about 2,400 to 7,900 more sign-ups.
- **Why check 5 switched:** with 183,945 pulls left and arm 21 about 6 standard errors ahead, no later stage could benefit from more data on the runners-up. ×0.05 would still have spent a few pulls on arms 12 and 0 (about 44 sign-ups lost in expectation). ×0.02 makes their bonus too small to overtake arm 21.
- **Validation:** on fresh worlds, ×0.02 lowered expected regret by 51.5 sign-ups (upper bound −44.8) and 95% CVaR by 167 (upper bound −95). Every one of the last 183,945 pulls went to arm 21. Stage 3.4 had put 13 of its 200,000 pulls elsewhere, so the switch changed the total by tens of sign-ups at most.
- **What this shows:** the value of exploring falls as the remaining budget shrinks, and a time-varying multiplier picks this up near the end of the horizon.

### The live run itself

- **The continuous run:** 983,945 pulls from 12 November 00:30 to 14 November 21:24 Singapore time (68 h 54 m). That averaged 3.97 pulls per second, including about 8 minutes of tuning pauses.
- **Retries:** 9 pulls had uncertain responses (14 retries in all). Each was resolved with the same request ID and counted once. No pull was lost or duplicated.

### Files

- [phase3/results/final_pulls.csv.gz](phase3/results/final_pulls.csv.gz): every pull, with arm, reward, server running total, model setting and save time.
- [phase3/results/final_summary.json](phase3/results/final_summary.json): integrity checks, totals, stages, per-arm rates with 95% intervals and P(best), and leader stability.
- [phase3/results/tuning_decisions.json](phase3/results/tuning_decisions.json): all five tuning decisions as the runner journaled them.
- These three files are made read-only from the database by `python phase3/export_results.py`. The full database (116 MB) and event log (1 GB) are too large for GitHub. The copies in `program/data/` are the 15,055-pull snapshot. Ask for the full files if you need them.
- `phase3/checklocalstatus.py` reports a run's progress, timing spread and tuning decisions from the local files, without network access.

## Continuous runs and optional tuning

Online execution is complete; see [Final results](#final-results-all-1000000-pulls) above. The stage reports
further down are historical snapshots taken during the run.

From the project root:

```bash
# Offline summary (default): no password or network needed
python3 phase3/main.py

# All remaining group allowance; Ctrl-C requests a graceful stop
python3 phase3/main.py --online

# Enable local tuning, replanning every 200,000 newly saved pulls
python3 phase3/main.py --online --auto-tune

# Optional cap on additional pulls in this invocation
python3 phase3/main.py --online --limit 10000 --auto-tune
```

Edit [phase3/config.py](phase3/config.py) or the first cell of
[GP3 Run.ipynb](program/GP3%20Run.ipynb). `MAX_PULLS_THIS_RUN=None` / `BUDGET=None`
means all remaining pulls. `TARGET_TOTAL_PULLS=None` uses the server's group-wide
cap of 1,000,000 **including past pulls**. Explicit limits can only reduce this
allowance. `ONLINE=False` and `AUTO_TUNE=False` are the shipped defaults; fixed UCB
uses multiplier 0.05 (`exploration=0.005`). Enter the account and password privately
at runtime. Never save the password in config, notebooks, logs or version control.

The CLI supports the same behavior:

```bash
cd program
python3 -m bandit run --online --group group19 --auto-tune
```

Omit `--budget` to use all remaining pulls. Without `--online` it only trains from
saved outcomes and recommends an arm. On this machine, Python's default CA file
is missing; for online commands use `SSL_CERT_FILE=/etc/ssl/cert.pem` as an
environment prefix, as in `SSL_CERT_FILE=/etc/ssl/cert.pem python3 phase3/main.py
--online` from the project root. TLS verification remains enabled.

### Long-running behavior

- One sequential driver; start spacing is at least 0.25 seconds. No concurrent HTTP
  calls or catch-up bursts. The teaching team's `server_pull.py` remains unchanged.
- Model loading uses SQL sufficient statistics, with only 24 arm states in Python.
  SQLite has a 4 MiB cache. Progress prints every 1,000 completed pulls. Notebook
  result previews and log-tail reads are bounded; raw history is streamed to disk.
- First Ctrl-C/SIGTERM requests a stop after the in-flight response has been saved.
  A second signal can force interruption. SIGKILL/power failure cannot be graceful;
  the pending arm, counter and UUID were durably stored before sending.
- Restart with the same account/database to recover the exact request first.
  Recovery counts toward the invocation limit. An absolute cap that excludes the
  pending request leaves it untouched until a suitable recovery run is requested.
- `MAX_RETRIES=None` retries uncertain responses until stopped, with a >=1-second
  cooldown and capped exponential backoff. A finite number limits retries.
  Authentication/counter rejection, local storage failure or history mismatch stops
  the driver safely; it never invents a fresh request to bypass an unresolved one.
- Every outcome is committed with SQLite `synchronous=FULL`; logs flush/fsync.
  Keep enough disk space for the growing database and JSONL log (potentially GBs).
  Do not run multiple drivers for one group, even with different database files.

### Optional tuning

The tuner evaluates the **whole remaining budget**, using candidate UCB multipliers
for the next 200,000 pulls and a learning baseline continuation afterwards. It
compares full expected regret, next-stage loss and weighted cumulative-regret CVaR.
Independent validation and stage/tail loss allowances govern parameter changes.
The initial evaluation runs once all arms have observations; subsequent evaluations
are scheduled every 200,000 newly saved pulls, and the schedule survives restart.

A disposable process receives only aggregate data, uses bounded arrays and has a
600-second limit. Timeout/failure retains the baseline; manual stop cancels and
reaps it. All choices are journaled in SQLite and the event log. With tuning off,
the explicitly configured fixed multiplier is used. NumPy is optional for fixed
runs and required for tuning. See [algorithm, CVaR definition, safeguards and
limitations](docs/tuning.md). This is approximate Bayesian rollout with empirical
risk screening, not a claim of globally optimal or time-consistent risk control.

### Focused validation

At the user's request, this change is checked with focused CVaR, recovery, stopping,
worker-lifecycle and entrypoint tests rather than a full-suite run. A synthetic
[million-row loading check](docs/performance/continuous-memory-check.json) and a
[20,000-pull fake-server soak](docs/performance/continuous-soak-check.json) exercise
bounded memory and real local durability without consuming experiment pulls.

### Phase 3, stage 2: UCB ×0.05 from 1,200 to 5,000 pulls

- **The run:** 3,800 pulls on 11 November, 21:38–22:05 Singapore time, in 26 minutes 29 seconds, with no retries. The multiplier stayed at 0.05 (`exploration=0.005`).
- **Sign-ups:** 92,750 from 380,000 new visitors (24.41%). Arm 21 received 3,583 of these pulls; arm 12 received 146.
- **Current leader:** arm 21 has 4,282 pulls and a 24.50% conversion rate; arm 12 has 313 pulls and a 23.63% rate. Arm 21's estimated P(best) is 99.965%, conditional on the stationary Beta-binomial model.
- **Verification:** server and local totals agree, every saved UCB choice replays, and there is no pending request. The original 1,200 records were preserved. See [stage2_summary.json](phase3/results/stage2_summary.json).
- **Speed:** the live run above used the old completion-based delay and achieved 2.39 pulls/second. The subsequent pacing change was verified with status calls only; it did not add pulls. The earlier stage-1 timing estimates below are historical.

### Phase 3, stage 1: UCB ×0.05 from 240 to 1,200 pulls

- **The run:** 960 pulls on 10 November, 21:43–21:48 Singapore time. It took 5 minutes 16 seconds, at 3.04 pulls per second, with no retries. Every pull is saved as UCB with `exploration = 0.005`.
- **Sign-ups:** 23,101 from 96,000 visitors (24.1%), against 15.6% in the pilot.
- **Arm 21 still leads, but by less.** It got 689 of the 960 pulls (72%). Its rate fell from 25.5% in the pilot to 24.4% since.
- **Arm 12 is now close behind.** It rose from 21.5% to 23.9% over 157 pulls. UCB's next pull goes to arm 12.
- **15 arms got no pulls**: the 15 with the lowest pilot rates, 18.1% and below.
- **The data checks are still normal.**
  - Noise is 0.95 times binomial; about 1 ± 0.08 is normal.
  - 0 of 24 arms moved by more than 2 standard errors between their first and last pulls.
  - All arms together moved −1.0 standard errors.

| Arm | Pulls (since pilot) | Pilot rate | Rate since pilot | Rate now (95% interval) | P(best) |
|---|---|---|---|---|---|
| 21 | 699 (689) | 25.5% | 24.4% | 24.5% (24.1–24.8%) | 97.5% |
| 12 | 167 (157) | 21.5% | 23.9% | 23.7% (23.1–24.4%) | 2.2% |
| 0 | 71 (61) | 22.0% | 23.1% | 22.9% (21.9–23.9%) | 0.2% |
| 5 | 29 (19) | 21.4% | 21.8% | 21.7% (20.2–23.2%) | <0.1% |

All 24 arms, with UCB scores and forecasts, are in [phase3/results/arms.csv](phase3/results/arms.csv), made by `phase3/explain.py`.

### UCB ×0.05 rather than Thompson Sampling

Thompson Sampling did best in phase 2's simulation, but the group chose UCB ×0.05 for the live run.

**Why:**

- **The expected gain is too small to see.**
  - In phase 2, Thompson Sampling beat UCB ×0.05 by 836 ± 114 sign-ups over the whole budget, about 0.003%.
  - Luck alone moves the live total by about ±4,300 sign-ups (one standard deviation, for 100 million visitors at about 24.5%).
  - So nobody could tell from the result which method had been used.
- **UCB is verified in the code that runs live.** `phase3/check.py` confirms each pull goes to the choice of `program/bandit`'s `UCBModel(exploration=0.005)`. `program/bandit` has no Thompson model. Using it would mean new, untested code, on a budget that can't be redone.
- **Every UCB choice can be explained and checked.** UCB has no randomness, so each choice follows from the saved data. Thompson Sampling's choices are random draws.
- **UCB is in the course content; Thompson Sampling isn't.**

**What UCB ×0.05 gave us in stage 1 that Thompson Sampling wouldn't have:**

1. **More data on the runners-up.** UCB put 271 of the 960 pulls on arms other than 21. For comparison, `explain.py` simulates the same 960 pulls 500 times from the pilot's data. Each arm's true rate is set to its current estimate.

   | | Sign-ups | Pulls not on arm 21 | Arm 12 | Arm 0 |
   |---|---|---|---|---|
   | Actual run | 23,101 | 271 | 157 | 61 |
   | UCB ×0.05 (simulated) | 23,115 | 233 | 128 | 53 |
   | Thompson Sampling (simulated) | 23,346 | 80 | 42 | 22 |

   - The simulated UCB run is close to the real one, so the comparison is fair.
   - Thompson Sampling would have given arm 12 about 42 pulls instead of 157. Its 95% interval would then be about ±1.2 points instead of ±0.65. The extra pulls are what pin down how close arm 12 is to arm 21.
2. **A reason for every pull.** [phase3/results/decisions.csv](phase3/results/decisions.csv) records each pull's mean, bonus, score, runner-up and margin.
   - Replaying the database gives the same 960 choices.
   - 689 pulls exploited: arm 21 had the highest mean before every pull. The other 271 explored.
   - Judged by the means at the time, exploring cost about 390 sign-ups.
   - Thompson Sampling's choices are random draws, so they can't be explained one by one.
3. **A forecast that can be checked.** Before the run, the pilot data forecast that arm 21 would get 926 of the 960 pulls. It also forecast that arm 0 would first be pulled again at pull 314. In fact arm 21 got 689, and arm 0 came back at pull 262. The gap shows what changed: arm 21's rate fell and arm 12's rose.
4. **An explicit list of dropped arms.** If rates hold:
   - arm 9 comes back at about pull 6,600
   - arms 18, 14 and 3 come back at about pulls 85,000–900,000
   - the other 11 arms (13.3% and below) never come back within the budget

**What it costs:**

- **Sign-ups:** in the simulation above, Thompson Sampling earned about 230 more over these 960 pulls, about 1%. Phase 2 puts the gap over the whole budget at 836 ± 114.
- **The score isn't a confidence bound.** The ×0.05 bonus was tuned by simulation. Unlike standard UCB1's (×1), it isn't a calibrated confidence bound, so call the score an "optimistic score", not a confidence limit.
- **Dropped arms stay dropped.** If rates hold, UCB ×0.05 never retries the 11 dropped arms within the budget. Each had under a 0.1% chance of being best, but Thompson Sampling would always keep a small chance of trying them again.

Thompson Sampling's own summary is each arm's chance of being best, and that is still reported. It comes from the Beta posteriors whichever method makes the pulls; it's the P(best) column above.

### Phase 2 findings (offline simulation)

Phase 2 drew 200 possible worlds of true conversion rates from the pilot's Beta posteriors. In each world it played 56 combinations out to 1,000,000 pulls. Each combination is a number of uniform pulls per arm, then UCB, ε-greedy or Thompson Sampling. The top 5, plus each method's best, were then rerun on 200 fresh worlds that the ranking never saw. Details are in [phase2/README.md](phase2/README.md).

- **Start straight from the pilot.** Adding uniform pulls before the method only cost sign-ups. Going to 100 per arm cost about 21,000 more, whichever method followed.
- **Three settings lead.** Thompson Sampling, UCB ×0.05 and UCB ×0.02 each lost between about 540 and 2,550 sign-ups on the fresh worlds. That is compared with always pulling the true best arm, which would earn about 25.6 million.
- **UCB ×0.02 has a big downside.** Its average is close to the leaders, but it lost about 448,000 sign-ups in its worst fresh world. UCB ×0.05 never lost more than about 7,800.
- **Smaller multipliers are worse.** UCB ×0.01 and ×0.005 lost 24,000–45,000 on average, and 1.35–1.8 million in their worst worlds.
- **ε-greedy and standard UCB1 fall far behind.** The best ε-greedy setting (ε = 0.01) lost about 104,000; standard UCB1 (×1) lost about 719,000.

| Fresh-world rank | Combination | Sign-ups lost vs best arm (± 2 SE) | Worst world |
|---|---|---|---|
| 1 | Thompson Sampling, from the pilot | 542 ± 83 | 4,235 |
| 2 | UCB ×0.05, from the pilot | 1,378 ± 182 | 7,783 |
| 3 | UCB ×0.02, from the pilot | 2,547 ± 4,481 | 447,523 |
| 4 | Thompson Sampling, 25 per arm first | 3,903 ± 68 | 7,651 |
| 5 | UCB ×0.02, 25 per arm first | 6,807 ± 6,275 | 631,108 |
| 6 | ε-greedy 0.01, from the pilot | 103,918 ± 5,012 | 536,188 |

Charts: [phase2/figures/findings.png](phase2/figures/findings.png) and [phase2/figures/top5_expected_vs_worst.png](phase2/figures/top5_expected_vs_worst.png).

### Phase 3 plan: the rest of the pulls, starting with UCB ×0.05 until 1,200

- **Where:** [phase3/](phase3/README.md) runs it, reusing phase 1's driver. Stage 1 is done; see the results above.
- **What:** UCB pulls the arm with the highest `mean + 0.05 × √(2 ln t / n)`, starting from the pilot data with no more uniform pulls. In `program/bandit` this is `UCBModel(exploration=0.005)`, because exploration = 2 × multiplier².
- **Why UCB ×0.05:** it was the best course method on the fresh worlds, and its worst case was small. It averaged 836 ± 114 sign-ups behind Thompson Sampling, about 0.003% of the total. UCB ×0.02 averaged about the same but had a far larger worst case.
- **Checkpoint:** after 960 more pulls (under 0.1% of the budget), recheck how it is going before using more of the budget.
- **Timing:** stage 1 ran at 3.04 pulls per second. At that speed, the 998,800 pulls left take about 91 hours non-stop. New pulls close on 15 November 2026 at 23:59 Singapore time, so the pulls need to start by about 04:41 on 12 November, Singapore time, and then keep going.

### Phase 1 pilot

- **Arm 21 leads** at 25.5% (95% interval 22.9–28.3%), with a 93% chance of being the best arm.
- **Arms 0, 12, 5 and 16** (21.3–22.0%) still have a small chance of being best.
- **The other 19 arms** each have under a 0.5% chance of being best. Rates range from 7.1% to 25.5%.
- **The data checks are normal.**
  - Pull-to-pull variance is 0.99 times what binomial noise predicts; about 1 ± 0.19 is normal.
  - 2 of 24 arms moved by more than 2 standard errors between their first and last 5 pulls; 0 to 3 is normal.
  - All arms together moved 0.0 standard errors.

| Band | Arm | Sign-ups / 1,000 visitors | Rate | 95% interval | P(best) |
|---|---|---|---|---|---|
| Leader | 21 | 255 | 25.5% | 22.9–28.3% | 93.0% |
| In contention | 0 | 220 | 22.0% | 19.5–24.7% | 2.8% |
| In contention | 12 | 215 | 21.5% | 19.1–24.2% | 1.4% |
| In contention | 5 | 214 | 21.4% | 19.0–24.1% | 1.2% |
| In contention | 16 | 213 | 21.3% | 18.9–23.9% | 1.0% |
| Behind | 22 | 208 | 20.8% | 18.4–23.4% | 0.4% |
| Behind | 20 | 203 | 20.3% | 17.9–22.9% | 0.2% |
| Behind | 6 | 197 | 19.7% | 17.4–22.3% | <0.1% |
| Behind | 19 | 197 | 19.7% | 17.4–22.3% | <0.1% |
| Behind | 9 | 181 | 18.1% | 15.8–20.6% | <0.1% |
| Behind | 18 | 170 | 17.0% | 14.8–19.5% | <0.1% |
| Behind | 14 | 167 | 16.7% | 14.5–19.1% | <0.1% |
| Behind | 3 | 162 | 16.2% | 14.0–18.6% | <0.1% |
| Behind | 2 | 133 | 13.3% | 11.3–15.5% | <0.1% |
| Behind | 8 | 129 | 12.9% | 11.0–15.1% | <0.1% |
| Behind | 17 | 129 | 12.9% | 11.0–15.1% | <0.1% |
| Behind | 15 | 126 | 12.6% | 10.7–14.8% | <0.1% |
| Behind | 13 | 120 | 12.0% | 10.1–14.2% | <0.1% |
| Behind | 23 | 106 | 10.6% | 8.8–12.7% | <0.1% |
| Behind | 7 | 93 | 9.3% | 7.7–11.3% | <0.1% |
| Behind | 11 | 82 | 8.2% | 6.7–10.1% | <0.1% |
| Behind | 10 | 80 | 8.0% | 6.5–9.8% | <0.1% |
| Behind | 1 | 75 | 7.5% | 6.0–9.3% | <0.1% |
| Behind | 4 | 71 | 7.1% | 5.7–8.9% | <0.1% |

**How these were calculated:**
- **95% interval:** the Beta(1 + sign-ups, 1 + non-sign-ups) posterior for each arm.
- **P(best):** the share of 400,000 posterior draws in which that arm has the highest rate.
- **Bands:** "In contention" means P(best) is at least 0.5%; "Behind" means it is below that.

**Files:**
- The chart is [phase1/figures/arm_ci.png](phase1/figures/arm_ci.png), made by `phase1/plot_arm_ci.py`.
- Every pull is in `program/data/history.sqlite3`, and the event log is in `program/data/history.online.jsonl`.
- Phase 2 draws its simulated worlds from these posteriors; see [phase2/README.md](phase2/README.md).

---

This project selects among 24 website variants to maximize cumulative sign-ups.
Each real pull assigns 100 visitors to one arm, numbered 0 through 23. The shared
group limit is 1,000,000 pulls, including tests and calls from other sessions.

The framework adds saved-history learning, uniform exploration, configurable UCB,
bounded online execution, recovery, and an append-only online event log. The
teaching team's `server_pull.py` and `GP3 Starter.ipynb` remain unchanged.

## Requirements and layout

- Python 3.9 or later on macOS/Linux. The framework, CLI and automated tests use
  only the standard library. The operational notebook also needs a Jupyter
  environment, which supplies IPython display; pandas/matplotlib are not required.
- A normal internet connection and the assigned group account for online mode.
- One sequential driver for the entire group, with one shared canonical database.

```text
project3/
├── README.md
├── doc/GP3 Multi-Armed Bandit Project.pdf
├── program/
│   ├── server_pull.py          # Supplied HTTP client, unchanged
│   ├── GP3 Starter.ipynb       # Supplied examples, unchanged
│   ├── GP3 Run.ipynb           # Configure, run, and inspect experiments
│   ├── bandit/
│   │   ├── common.py          # Assignment constants and response validation
│   │   ├── models.py          # Uniform and UCB model state/selection
│   │   ├── storage.py         # SQLite history, pending requests and local lock
│   │   ├── client.py          # Paced access to the supplied helper
│   │   ├── audit.py           # Append-only JSONL online event logger
│   │   ├── runner.py          # Public experiment and import functions
│   │   └── __main__.py        # Command-line interface
│   ├── tests/                # Entirely offline verification
│   └── data/                 # Saved pulls and event log; the pilot's files are committed
└── docs/superpowers/plans/    # Implementation decisions and verification record
```

Run the examples below from `project3/program`. The default database is always
`program/data/history.sqlite3`, independent of the current working directory when
using the Python API. Use an explicit `db_path` / `--db` for a different location.

## Run from the notebook

Open `program/GP3 Run.ipynb` in Jupyter or a notebook-capable editor. Select a
Python 3.9+ kernel and work through the cells in order:

1. **Settings:** choose `MODEL_NAME` (`"uniform"` or `"ucb"`), set
   `UCB_EXPLORATION`, `BUDGET`, `ONLINE` and `AUTO_TUNE`. Defaults are UCB
   with exploration 0.005, BUDGET=None (all remaining), ONLINE=False and
   AUTO_TUNE=False. Account username, paths, request timing and display
   limits are also centralized in this first code cell.
2. **Setup:** load the existing framework and local display helpers. No HTTP calls
   occur. Relative data paths resolve against `program/`, matching the CLI.
3. **Run the experiment:** offline mode trains from history and recommends an
   arm. For `ONLINE=True` and a positive or None budget, enter the group username (unless
   configured) and the password through hidden input. The password is never a
   configuration value, notebook global, or displayed result.
4. **Refresh saved results and arm statistics:** view group identity, local totals,
   pending recovery, all 24 arms, and recent saved pulls. The table includes pull
   counts, visitors, sign-ups, conversion rates, allocation shares, and UCB indices
   when selected. It reopens SQLite read-only every time, including after a failed
   or interrupted run. It does not make requests even if `ONLINE=True`.
5. **Refresh the online log:** view a bounded number of recent event lines with
   request IDs, retries and outcomes. Missing logs and partial final lines are
   handled without creating new requests.

Execute the settings cell again after editing it. Refreshing the viewing cells is
safe; **rerunning the online execution cell can spend another budget**. The latest
run summary is cleared before each attempt, so a failed run cannot show a previous
success as its result. Viewing cells can also run directly after setup without
executing an experiment. Invalid budget, account or network settings do not block
local views; the log viewer is also independent of model settings. From an empty history, views show empty totals and all
24 arms with zero samples.

The notebook is delivered with outputs cleared. Save it after a run to retain
displayed tables. To export an analysis using the saved outputs:

```bash
jupyter nbconvert --to html "GP3 Run.ipynb"
```

Do not add `--execute` or enable execution in an export dialog. The supplied
`GP3 Starter.ipynb` remains unchanged.

## Quick start: offline first

```bash
cd /path/to/project3/program
python3 -m bandit run --model uniform --budget 100
python3 -m bandit run --model ucb --exploration 2.0 --budget 100
```

Without `--online`, both commands load **all saved real results**, rebuild the
model, and report the next arm. They make no network calls, generate no simulated
outcomes, and consume no group budget. An empty history recommends arm 0.

The budget only limits online execution; it does not limit how much saved history
is used for training. `--online --budget 0` also sends no requests.

## Python API

```python
from getpass import getpass
from bandit import UCBModel, UniformModel, run_experiment

online = False
username = input("Group username: ").strip() if online else None
password = getpass("Group password: ") if online else None

try:
    summary = run_experiment(
        model=UCBModel(exploration=2.0),  # Or UniformModel(), "uniform", "ucb"
        budget=100,                    # Maximum completed pulls in this run
        online=online,
        db_path="data/history.sqlite3",
        username=username,
        password=password,
        interval=0.25,
        timeout=10.0,
        max_retries=2,
    )
    print(summary["completed_pulls"], summary["next_arm"])
finally:
    password = None
```

Set `online=True` only when you intend to consume real experimental budget. The
model selects each arm internally from saved history and newly committed results.
It is refitted at the beginning of every run, so switching from uniform to UCB
reuses the same observations without counting them twice.

The returned summary contains model settings, per-arm counts and conversion
rates, locally observed sign-ups, completed pulls, stop reason, pending recovery
state, and the next arm. `history_signups` covers locally recorded observations;
it can differ from the group's server `NetReward` when historical calls are missing.
`server_status` is the latest known snapshot (or `None` when none was requested).
When a pending request exists, `next_arm` identifies that request's arm because
recovery must happen before a fresh decision.

## Online execution

These commands make real requests and consume the group's budget:

```bash
python3 -m bandit run --model uniform --budget 240 --online --group YOUR_GROUP
python3 -m bandit run --model ucb --exploration 2.0 --budget 1000 --online --group YOUR_GROUP
```

The CLI prompts privately for the password. It also supports a `GP3_PASSWORD`
environment variable for a controlled local environment; never place its value in
saved code, shell scripts, logs, URLs or submitted files. There is no password
command-line argument. The server defaults to the teaching team's HTTPS address.

- Budget means the maximum number of successfully resolved pulls in **this run**.
- Resolving a pending request from a previous run counts as one completed pull in
  the new run, even if the server had already recorded it. Retrying its UUID does
  not consume additional pull slots or intentionally create additional pulls.
- The driver checks server usage before starting fresh requests and respects the
  smaller of the requested budget and the remaining group allowance.
- Every HTTP call, including status, starts at least 0.25 seconds after the
  preceding call starts. Calls remain sequential: the preceding response must
  finish first. Network time and local work count toward this interval, rather
  than adding another 0.25 seconds after a response. `--interval` can increase
  this spacing, never reduce it. Late requests never trigger catch-up bursts;
  the next interval always starts from the actual dispatch time.
- With a finite `max_retries`, an uncertain response is retried at most that many
  times after the first attempt. None retries until stopped. Every retry preserves
  identity and waits at least one second, with capped backoff for continuous runs.
- New requests stop at the assignment deadline, **15 November 2026, 23:59
  Singapore time**, or when the server reports closure. Existing pending requests
  may still be submitted for recovery; the server decides whether recovery is
  available after closure.
- Local file locking prevents two drivers using the same resolved database path.
  It cannot coordinate different computers or separate database copies. All group
  members must use one driver and avoid simultaneous calls from the starter.

Online errors stop the run. Earlier committed results remain available. Server
state remains authoritative if another group member has used the account.

### Throughput and the deadline

On 11 November, 120 sequential status-only requests compared the old and new
schedulers in alternating blocks. Measured status throughput rose from 2.79 to
3.60 requests/second; the shortest start interval was 0.25025 seconds and no
one-second window contained more than four requests. The server stayed at 5,000
pulls and 119,597 sign-ups. SQLite FULL transactions and per-event log fsync remain
enabled, as do the one-second retry cooldown and the deadline check after waiting.

Status throughput is not a measured live-pull rate. Replaying the timing of the
previous 3,800 real pulls predicts about 3.68 pulls/second with the new scheduler;
the assumptions and raw benchmark are in the [performance report](docs/performance/2026-11-11-online-pacing.md).
At the benchmark time (11 November, 22:20 Singapore time), completing the remaining
995,000 pulls required an average of at least 2.83 pulls/second through the deadline.
At a sustained 3.2 pulls/second they take 86.4 hours, leaving about 11.3 hours for
interruptions. These are forecasts, not guarantees; include later start time,
server latency, retries, sleep/offline time, and pauses in the next run's estimate.

On this macOS installation, Python's default CA file is missing. The benchmark
used `SSL_CERT_FILE=/etc/ssl/cert.pem` for this process to load the existing system
CA bundle, keeping certificate and hostname verification enabled. No credentials
or authentication headers are included in the benchmark artifacts.

## Persistence and existing results

The SQLite database is the source of truth, with three responsibilities:

1. Bind history to one group username and one server address.
2. Append each completed response immediately, uniquely keyed by its server `Pull`.
3. Persist a pending request's UUID, counter, arm and model settings **before**
   sending it, then save the result and clear pending in a single transaction.

Results have the original fields `Arm`, `Reward`, `NetReward`, and `Pull`.
Additional database metadata includes save time, model, parameters and request ID.
Passwords and request headers are not persisted. Repeated identical imports are
ignored; conflicting responses for the same pull index are rejected. An import
batch is transactional, so invalid input rolls back that entire batch.

To append actual results already held in a notebook:

```python
from bandit import save_results

# actual_saved_results is your list of real response dictionaries.
inserted = save_results(
    actual_saved_results,
    username="YOUR_GROUP",
    db_path="data/history.sqlite3",
)
print("New observations saved:", inserted)
```

For a single actual response use `save_results([result], ...)`. This supports
manual imports, but using the runner for new calls additionally protects the
request identity before transmission. Do not import the illustrative values in
the supplied starter: they are not observations from your group's experiment.

Import/export JSONL (one original response dictionary per line):

```bash
python3 -m bandit import-results actual_results.jsonl --group YOUR_GROUP
python3 -m bandit export-results results_export.jsonl
```

Exports use a new file and refuse to overwrite an existing file. Historical gaps
are permitted because some earlier responses may be unavailable, but the model
can learn only from the observations you actually saved. A status response alone
cannot reconstruct missing per-arm results. Back up the database and logs while
the driver is stopped, and keep backups private to the group.

## Online pull log

The default append-only log is `program/data/history.online.jsonl`, beside the
database. Override it with `log_path=...` or `--log ...`.

Events include `run_started`, `status`, `pull_prepared`, `pull_attempt`,
`pull_uncertain`, `pull_completed`, `pull_cancelled`, `run_finished`, and `run_failed`.
Every event contains a UTC timestamp and a run UUID. Request events include arm,
request UUID, expected counter, model and settings; completed events include the
original response. Retries carry attempt numbers and whether another retry is
scheduled. Each event is flushed to disk as it is appended.

The deadline is checked again after pacing, immediately before a fresh request
is transmitted. If that wait crosses the deadline, the known-unsent request is
cancelled and logged without consuming a pull or leaving a pending recovery.

Error events contain the exception type, not arbitrary server messages or
credentials. Offline runs do not write online events. The database is the
authoritative training history; the JSONL file is the operational audit trail.
A process killed after committing a result but before writing its completion
event can leave the log incomplete while the database remains correct.

## Recovery after interruption

Rerun the same database, group and server with `online=True` and a positive or None budget.
The driver first reuses the saved UUID, counter and arm. An identical retry
retrieves an already completed result, or performs the one intended pull if it
had not completed. Only after committing that result may a new arm be selected.
The recovery request retains its original model metadata even if the new run
uses another model.

If retries are exhausted, the pending request stays in SQLite. Offline mode can
inspect it without contacting the server. Do not delete it, change its arm, or
rerun `configure()` manually to bypass it. For an explicit rejection or counter
conflict, coordinate with group members and the teaching team before changing
state. The framework deliberately preserves evidence instead of guessing which
request should be discarded. Do not switch to another database to bypass it.

## Model settings and interpretation

**UniformModel** chooses the arm with the fewest saved pulls, breaking ties by
the lowest arm ID. With empty history, this gives round-robin balanced exploration.
With uneven historical data, it first catches up under-sampled arms; it does not
sample each arm independently at random.

**UCBModel(exploration=2.0)** tries all unseen arms first and then maximizes:

```text
mean_sign_up_rate[i] + sqrt(exploration * log(total_pulls) / pulls[i])
```

The observation unit is one 100-visitor batch. Its reward is `Reward / 100`, so
`pulls[i]` counts batches, not visitors. The class constructor default 2.0 is the usual bounded-reward
UCB1 coefficient; smaller positive values favor exploitation. Scores are selection
indices and may exceed 1; they are not conversion probabilities or a final
statistical confidence statement. Unobserved scores are shown as `null` in JSON.

Training aggregates pull counts and sign-ups from saved records. No separate
optimizer or serialized model is needed for these fixed-policy baselines; policy state is rebuilt from
history and updated after each completed pull. These baselines assume sufficiently
stable reward behavior. Historical replay trains a policy but does not provide an
unbiased estimate of how a different policy would have performed online.

## Verification

```bash
python3 -m unittest discover -s tests -v
```

Tests exercise models, storage, real helper recovery with fake HTTP responses,
pacing with a controllable clock, the audit log, and CLI import/export. They do not
call the live server or consume experimental pulls.

## Submission reminders

Submit a PDF report (at most four pages excluding appendices) and an HTML analysis
file separately on Canvas, one submission per group, by the deadline. Include
members' names, student numbers and group username on the cover. Report method,
pull usage, total sign-ups and evidence for the final selection. Include prompts
used with an LLM. Export the finished notebook without `--execute` to avoid extra
live calls, and verify that no password appears in either submitted file.
