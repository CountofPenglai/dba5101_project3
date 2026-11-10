# Phase 3: The Rest of the Pulls

Phase 3 makes the rest of the group's pulls, using UCB from the pilot data onward. It starts with UCB ×0.05 until the database holds 1,200 pulls: the pilot's 240 plus 960 more. The group then rechecks before going further.

**These are real pulls. They use the group's budget and can't be undone.** Only one person should run this, and nobody else should use the account while it runs.

## The plan

1. **Stage 1: UCB ×0.05 to 1,200 pulls.** Done on 10 November; the results are in the [root README](../README.md).
   - Each pull goes to the arm with the highest `mean + 0.05 × √(2 ln t / n)`. Here `t` is all pulls so far, and `n` is that arm's pulls.
   - This is `program/bandit`'s `UCBModel(exploration=0.005)`, because exploration = 2 × multiplier².
   - There are no more uniform pulls, because phase 2 found they only cost sign-ups.
   - Why ×0.05: see the phase 2 findings in the [root README](../README.md).
2. **Recheck as a group** (see [The recheck at 1,200 pulls](#the-recheck-at-1200-pulls)).
3. **Continue:** raise `TARGET_TOTAL_PULLS` for the next stage, up to 1,000,000.

## Timing

- **Stage 1** ran on 10 November, 21:43–21:48 Singapore time. Its 960 pulls took 5 minutes 16 seconds, at 3.04 pulls per second, with no retries.
- **The 998,800 pulls left** take about 91 hours non-stop at that speed.
  - New pulls close on 15 November 2026 at 23:59 Singapore time. So the pulls need to start by about 04:41 on 12 November, Singapore time, and then keep going.
  - The recheck and any pauses come out of that margin.
  - If time runs out, the run stops by itself at the deadline, with stop reason `deadline_reached`.

Every live run prints its own speed and the hours left until new pulls close. `python explain.py` recomputes both from the event log.

## How to run it

Run these from this folder. Python 3.9 or later is enough, with nothing extra to install.

1. **Check the code (no pulls):** `python check.py` takes about 30 seconds. It runs `main.py` against a fake server, on a temporary copy of the database, and confirms that:
   - the offline run sends no requests
   - each pull goes to the arm that `UCBModel(exploration=0.005)` picks from the pulls before it, and is saved with that setting
   - a run stops exactly at `TARGET_TOTAL_PULLS`; a rerun at the target makes no pulls; raising the target continues from the saved pulls
   - a lost response is retried with the same request, so it counts as one pull
   - it stops before pulling if the server has pulls the database doesn't
   - bad settings stop it before any request
   - the real database is unchanged
2. **Check the setup:** leave `ONLINE = False` and run `python main.py`. This sends no requests. It should show 240 saved pulls, 960 left, and arm 21 as the next pull.
3. **Test with 1 live pull:** set `ONLINE = True`, leave `MAX_PULLS_THIS_RUN = 1`, and run it again. Enter the group password when asked. Before going further, check that:
   - `Server pulls used` reads `240`, the same as `Saved locally`
   - the `Result:` line shows arm `'21'` and `Pull` `240`, with `NetReward` equal to 3,746 plus its `Reward`
   - it reports `Completed 1 pulls` with stop reason `budget_complete`
4. **Run to 1,200:** only if the test looks right, set `MAX_PULLS_THIS_RUN = 960` and run it again. It makes the remaining 959 pulls and stops at 1,200.

Running it again after that is safe. It never goes past `TARGET_TOTAL_PULLS`, so it makes no more pulls. Set `ONLINE = False` when you're done.

5. **Explain the run (no pulls):** `python explain.py` takes about 30 seconds and needs numpy. It reads the database read-only and:
   - replays every pull since the pilot, and confirms that `UCBModel` makes the same choices
   - counts exploit pulls (to the arm with the highest mean) and explore pulls, with what exploring cost
   - gives every arm's pilot rate, rate since the pilot, UCB score, chance of being best, and the forecast of its next pull
   - simulates the same pulls with UCB and with Thompson Sampling, for comparison
   - reports each run's speed from the event log

   It writes `results/decisions.csv` (one row per pull) and `results/arms.csv` (one row per arm). Stage 1's printout is in `results/explain.txt`.

**If a run stops or a request times out,** run the same command again. It recovers any unfinished request first, then continues to the target. Don't delete the database or point to a new one to get around an error.

## Settings

All settings are in `config.py`. The password never goes there. Type it when asked, or set the `GP3_PASSWORD` environment variable.

| Setting | Default | What it controls |
|---|---|---|
| `UCB_MULTIPLIER` | `0.05` | The UCB bonus multiplier. Every run prints it, with the `exploration` value it gives |
| `ONLINE` | `False` | `True` sends real requests that use the budget |
| `TARGET_TOTAL_PULLS` | `1200` | Stop when the database holds this many pulls, the pilot's included |
| `MAX_PULLS_THIS_RUN` | `1` | Most pulls in each run: `1` for the test, then `960` |
| `GROUP_USERNAME` | `"group19"` | The group account; blank means it asks |
| `DB_PATH` | `../program/data/history.sqlite3` | Saved results, shared with phases 1 and 2 |
| `LOG_PATH` | `None` | Event log; `None` saves it beside the database |
| `REQUEST_INTERVAL` | `0.25` | Seconds between calls, which is also the minimum |
| `REQUEST_TIMEOUT` | `10.0` | Seconds to wait for each response, up to 60 |
| `MAX_RETRIES` | `2` | Retries of an uncertain request, using the same request ID |
| `ALLOW_UNSAVED_SERVER_PULLS` | `False` | `True` continues even if the server has pulls the database doesn't |

Before pulling, the script compares the server's pull count with the database and stops if they don't match, as phase 1 did.

## Reading the results

Each saved pull prints phase 1's `Result:` line with the server's response, followed by running totals. At the end, every run prints:

- **A table of all 24 arms**, highest UCB score first. It shows each arm's pulls, sign-ups, rate, UCB score and pulls since the pilot. The arm marked `<- next pull` is UCB's next choice.
- **Since the pilot:** pulls, sign-ups and the rate since pull 240, and which arm got the most of them.
- **Speed:** pulls per second, how long the rest of the budget would take, and the hours until new pulls close.
- **Phase 1's noise and stability checks**, now over every saved pull, with the same normal ranges:
  - Noise: the variance ratio should be about 1, within the range printed beside it.
  - Stability: 0 to 3 arms moved by more than 2 standard errors.
  - All arms together: a move between −2 and 2.

## The recheck at 1,200 pulls

Suggested questions for the group:

- **Concentration:** is UCB putting most pulls on one arm, and is it arm 21, the pilot's leader?
- **Leader:** has any arm's rate moved enough to change the leader?
- **Checks:** are noise and stability still normal?
- **Speed:** does the printed speed leave enough time to finish the budget before the deadline?

Then set the next `TARGET_TOTAL_PULLS` and `MAX_PULLS_THIS_RUN`, and run `python main.py` again.

## How it works

- **Reused code:** `main.py` loads `phase1/main.py`. From it, phase 3 reuses the Windows database lock, the server check, safe retries, progress lines and error messages. Only the model, the stopping rule and the final report are new. Keep `phase1/main.py` where it is, because phase 3 loads it from there.
- **Database:** it uses the same database as phases 1 and 2, `program/data/history.sqlite3`. Each pull is saved with model `ucb` and `{"exploration": 0.005}`, so the pilot's pulls and phase 3's can be told apart.
