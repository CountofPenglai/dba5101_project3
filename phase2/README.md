# Phase 2: Simulate the Combinations

Phase 2 is offline. It makes no pulls and only reads phase 1's database, so it is safe to run at any time.

## The plan

1. **Collect 240 real pulls** (phase 1): 10 pulls on each of the 24 arms.
2. **Estimate plausible conversion rates.** Each arm gets a Beta distribution built from its sign-ups and non-sign-ups: `Beta(1 + sign-ups, 1 + non-sign-ups)`. An arm with 150 sign-ups from 1,000 visitors gets `Beta(151, 851)`.
3. **Simulate the combinations.** Each one is a uniform total combined with a method setting. The original plan had 40 combinations: UCB with multipliers 0.05–1, and ε-greedy. In the first run, UCB ×0.05 won at the edge of that range, so smaller multipliers (0.005–0.02) and Thompson Sampling were added, making 56:

   | | Uniform totals (pulls per arm) | Parameter values |
   |---|---|---|
   | UCB (32) | 10, 25, 50, 100 | Bonus multiplier 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1 |
   | ε-greedy (20) | 10, 25, 50, 100 | ε 0.01, 0.025, 0.05, 0.1, 0.2 |
   | Thompson Sampling (4) | 10, 25, 50, 100 | No parameter |

4. **Compare and validate.** Rank all of them by expected sign-ups. Then rerun the top 5, plus the best setting of any method not among them, on fresh simulated worlds to check the leaders hold up.

## How the simulation works

- **Worlds.** A world is one plausible set of 24 true conversion rates, drawn from the arms' Beta distributions. The default is 200 worlds. All 40 combinations run on the same worlds, so their differences come from the method, not from luck in the worlds.
- **Starting point.** Every world starts from the real pilot data, just as the live run will.
- **Uniform phase.** Each arm is topped up to the uniform total with simulated pulls. At 10 per arm, the 240 real pulls already reach that total, so no pulls are added. At 100 per arm, 2,160 pulls are added.
- **Method phase.** The method makes every remaining pull, one at a time, until the budget reaches 1,000,000 pulls (real pulls included). Each pull draws `Binomial(100, true rate)` sign-ups.
  - **UCB** pulls the arm with the highest `mean + multiplier × √(2 ln t / n)`. Here `t` is the pulls so far, and `n` is that arm's pulls. This is the same as `program/bandit`'s `UCBModel(exploration = 2 × multiplier²)`, so a multiplier of 0.05 means `exploration = 0.005`.
  - **ε-greedy** pulls a random arm (any of the 24) with probability ε. Otherwise, it pulls the arm with the highest mean.
  - **Thompson Sampling** draws a rate from every arm's `Beta(1 + sign-ups, 1 + non-sign-ups)` before each pull, then pulls the arm with the highest draw. It uses exact Beta draws, not an approximation. It has no parameter to tune. `program/bandit` has no Thompson model yet.
  - Ties go to the lowest arm number in UCB and ε-greedy. Thompson's draws are continuous, so ties don't arise.
- **Score.** The score is expected sign-ups. "Lost vs best arm" is how many fewer sign-ups the simulated pulls earned than always pulling that world's true best arm. Lower is better. The real pilot's pulls are already made, so they count the same for every combination and are left out.
- **Validation.** The leader is the best of 56 on the same worlds, which flatters it slightly. So the top 5, plus each method's best if it isn't among them, are rerun on 200 new worlds that the ranking never saw.

## How to run it

Run these from this folder. It needs Python 3.9 or later and numpy.

1. **Check the simulator:** `python main.py check` takes a few seconds. It confirms that:
   - the UCB choices match `program/bandit`'s `UCBModel` exactly
   - ε-greedy losses match hand formulas
   - Thompson matches a plain one-pull-at-a-time version pull for pull, and finds an obvious winner
   - the uniform phase tops arms up correctly
   - the Beta parameters are right
2. **Quick trial (optional):** `python main.py --reps 20 --total-pulls 50000` takes seconds. Use it to see the output format; its numbers don't mean much.
3. **Full run:** `python main.py` takes about 15 minutes on a 12-core machine. Thompson's exact Beta draws are the slowest part.
4. **Chart:** `python plot_results.py` reads `results/runs.csv` and writes `figures/findings.png`:
   - The left panel shows every setting starting straight from the pilot, with 95% intervals.
   - The right panel shows the extra sign-ups lost by adding uniform pulls first.
   - The title names the leaders and how far behind ε-greedy and standard UCB1 fall. It is computed from the data.

Run it only after phase 1 prints `0 pulls left in this phase` with all 24 arms at 10. If the arms have unequal pulls, it warns you.

## Settings

All settings are in `config.py`.

| Setting | Default | What it controls |
|---|---|---|
| `DB_PATH` | `../program/data/history.sqlite3` | Phase 1's database, opened read-only |
| `RESULTS_DIR` | `results` | Where the CSVs go; each run overwrites them |
| `PRIOR_A`, `PRIOR_B` | `1`, `1` | The Beta prior; `1, 1` treats every rate from 0–100% as equally likely beforehand |
| `UNIFORM_TOTALS` | `10, 25, 50, 100` | Pulls per arm before the method takes over |
| `UCB_MULTIPLIERS` | `0.005 … 1` | UCB bonus multipliers |
| `EPSILONS` | `0.01 … 0.2` | ε values |
| `THOMPSON` | `True` | Also simulate Thompson Sampling at each uniform total |
| `TOTAL_PULLS` | `1,000,000` | The whole budget, real pulls included. Lower it if the live run can't finish in time |
| `REPS` | `200` | Worlds for the comparison. More worlds give tighter error bars but take longer |
| `VALIDATE_TOP`, `VALIDATE_REPS` | `5`, `200` | How many leaders are rerun, and on how many fresh worlds |
| `SEED` | `5101` | The same seed and settings give the same results |
| `WORKERS` | `None` | Parallel processes; `None` means CPU count minus 1 |

## Reading the results

The console prints the following, in order:

1. **Step 2:** each arm's Beta distribution, its 95% interval, and `P(best)`, the chance that arm is the best one.
2. **Step 4a:** the 40 combinations ranked by expected sign-ups. Its columns are:
   - **Total sign-ups (expected):** real sign-ups so far plus the simulated pulls' expected sign-ups
   - **Lost vs best arm:** see Score above; `± 2 SE` shows how precise the average is
   - **Behind leader:** the paired gap to the top combination. `*` means the gap is within 2 standard errors, so these worlds can't separate the two combinations
   - **Picks best:** how often the arm with the highest final mean was the world's true best arm
   - **Best share:** the fraction of all pulls that went to the true best arm
3. **Step 4b:** the top 5 rerun on fresh worlds, with a verdict:
   - `CONFIRMED`: the leader leads again
   - `TIED`: the leader is within noise of the new leader, so either is defensible
   - `NOT CONFIRMED`: increase `REPS` and rerun before choosing
4. **Phase 3 settings:** what the chosen combination means for the live driver.

### Files in `results/`

| File | Contents |
|---|---|
| `posterior.csv` | Each arm's pilot data, Beta parameters, 95% interval and `P(best)` |
| `summary.csv` | The ranked comparison of every combination |
| `validation.csv` | The rerun of the leaders on fresh worlds |
| `console.txt` | The full printout of the last run |
| `runs.csv` | One row per combination per world, for your own tables and charts |
| `curves.csv` | Average sign-ups lost so far, at 40 points through the budget, for each combination |
| `run_info.json` | The settings, pilot totals and verdict for this run |

## Limits to state in the report

- **The figures are simulated.** Label them as simulated in the report, and report live results separately.
- **Binomial noise is assumed.** The Beta distributions assume each batch of 100 visitors behaves like independent coin flips. If phase 1's noise check showed variance well above binomial, the worlds are too certain.
- **Rates are assumed fixed.** Each world's rates don't change over time. Phase 1's stability check is the only evidence for that.
- **The pilot is small.** With 10 pulls per arm, the Beta distributions are wide. That is intended: the worlds cover the rates the pilot can't rule out.
