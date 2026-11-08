# GP3: Multi-Armed Bandit Experiment Framework

## Status: 240 of 1,000,000 pulls made

*Updated 8 November 2026, after the phase 2 offline simulation.*

| Pulls made | Visitors | Sign-ups | Pulls left |
|---|---|---|---|
| 240 (10 per arm) | 24,000 | 3,746 (15.6%) | 999,760 |

- **Done:** the phase 1 pilot (10 real pulls on each of the 24 arms) and the phase 2 offline simulation, which made no pulls.
- **Proposed next:** run UCB with bonus multiplier 0.05, starting straight from the pilot, until 1,200 pulls in total (960 more). Then recheck how it is going.
- **Open question:** how to approach Thompson Sampling, or whether to drop it, since it wasn't in the course content.

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

### Proposal: UCB ×0.05 until 1,200 pulls, then recheck

- **What:** UCB pulls the arm with the highest `mean + 0.05 × √(2 ln t / n)`, starting from the pilot data with no more uniform pulls. In `program/bandit` this is `UCBModel(exploration=0.005)`, because exploration = 2 × multiplier².
- **Why UCB ×0.05:** it was the best course method on the fresh worlds, and its worst case was small. It averaged 836 ± 114 sign-ups behind Thompson Sampling, about 0.003% of the total. UCB ×0.02 averaged about the same but had a far larger worst case.
- **Checkpoint:** after 960 more pulls (under 0.1% of the budget), recheck how it is going before using more of the budget.

### Open question: Thompson Sampling

Thompson Sampling lost the fewest sign-ups on the fresh worlds and had the smallest worst case. But it wasn't in the course content, and `program/bandit` has no Thompson model yet. The options are:

- use it live, after adding a Thompson model to `program/bandit` and explaining it in the report;
- keep it in the report only as a simulated comparison; or
- drop it.

In the simulation, choosing UCB ×0.05 instead cost about 836 ± 114 sign-ups.

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
   `UCB_EXPLORATION`, `BUDGET`, and `ONLINE`. The defaults are uniform, a budget of
   24, and `ONLINE=False`. Account username, paths, request timing and display
   limits are also centralized in this first code cell.
2. **Setup:** load the existing framework and local display helpers. No HTTP calls
   occur. Relative data paths resolve against `program/`, matching the CLI.
3. **Run the experiment:** offline mode trains from history and recommends an
   arm. For `ONLINE=True` and a positive budget, enter the group username (unless
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
- Every HTTP call, including status, is paced at least 0.25 seconds after the
  preceding call finishes. `--interval` can increase this delay, never reduce it.
- An uncertain response is retried at most `max_retries` times after the first
  attempt, waiting at least one second before retrying the same request.
- New requests stop at the assignment deadline, **15 November 2026, 23:59
  Singapore time**, or when the server reports closure. Existing pending requests
  may still be submitted for recovery; the server decides whether recovery is
  available after closure.
- Local file locking prevents two drivers using the same resolved database path.
  It cannot coordinate different computers or separate database copies. All group
  members must use one driver and avoid simultaneous calls from the starter.

Online errors stop the run. Earlier committed results remain available. Server
state remains authoritative if another group member has used the account.

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

Rerun the same database, group and server with `online=True` and a positive budget.
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
`pulls[i]` counts batches, not visitors. The default 2.0 is the usual bounded-reward
UCB1 coefficient; smaller positive values favor exploitation. Scores are selection
indices and may exceed 1; they are not conversion probabilities or a final
statistical confidence statement. Unobserved scores are shown as `null` in JSON.

Training aggregates pull counts and sign-ups from saved records. No separate
optimizer or serialized model is needed; the full policy state is rebuilt from
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
