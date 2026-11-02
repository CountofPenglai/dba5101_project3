# Phase 1: Initial Pilot

## The plan

Pull each of the 24 arms 100 times, in rotation from arm 0 to arm 23. That is 2,400 pulls (240,000 visitors), or 0.24% of the group's budget, and takes at least 10 minutes.

We start with a single live pull to confirm that live pulls work and return correctly. Only then do we make the remaining 2,399.

**These are real pulls. They use the group's budget and can't be undone.** Only one person should run this, and nobody else should use the account while it runs.

## Why we're doing it

The pilot is a safety check before we commit the other 997,600 pulls. It isn't how we find the best arm, because Thompson Sampling can do that without it. It gives us:

- **A noise check:** does each arm's variance look like normal binomial noise?
- **A stability check:** do each arm's first 50 and last 50 pulls look similar?
- **Real speed:** how long will the main run take, and when must it start?
- **Real rates to simulate from:** the final simulation has only been tested with 100 pulls per arm.
- **A fair comparison for the report:** every arm gets the same number of pulls.

In our simulations, which use invented rates, this pilot lost about 5,000–15,000 sign-ups compared with starting from 1 pull per arm. That is under 0.1% of the total. Going up to 400 pulls per arm lost a further 19,000–46,000 with no clear benefit, so we stop at 100.

## How to run it

Run these from this folder. Python 3.9 or later is enough, with nothing extra to install.

1. **Check the setup.** Leave `ONLINE = False` and run `python main.py`. This sends no requests. It creates an empty database if there isn't one yet.
2. **Test with 1 live pull.** Set `ONLINE = True`, leave `MAX_PULLS_THIS_RUN = 1`, and run it again. Enter the group username and password when asked. It makes one pull on arm 0. Before going further, check that:
   - `Server pulls used` reads `0`, unless the group has already saved earlier pulls
   - it reports `Completed 1 pulls` with stop reason `budget_complete`
   - arm 0 shows 1 pull with a plausible number of sign-ups, out of 100 visitors
   - the database now exists at `program/data/history.sqlite3`

   Ignore the speed line on this run, because one pull is too few to measure it.
3. **Finish the pilot.** Only if the test looks right, set `MAX_PULLS_THIS_RUN = 2400` and run it again. It makes the remaining 2,399 pulls and then stops.

Running it again after that is safe: it never takes an arm past `PULLS_PER_ARM`, so it makes no more pulls. Set `ONLINE = False` when you're done.

**If a run stops or a request times out,** run the same command again. It recovers any unfinished request first, then continues. Don't delete the database or point to a new one to get around an error.

## Settings

All settings are in `config.py`. The password never goes there. Type it when asked, or set the `GP3_PASSWORD` environment variable.

| Setting | Default | What it controls |
|---|---|---|
| `ONLINE` | `False` | `True` sends real requests that use the budget |
| `MAX_PULLS_THIS_RUN` | `1` | Most pulls in each run, so rerunning can make this many more: `1` for the test, then `2400` |
| `PULLS_PER_ARM` | `100` | The pilot's target for each arm |
| `GROUP_USERNAME` | `""` | The group account; blank means it asks |
| `DB_PATH` | `../program/data/history.sqlite3` | Saved results, shared with later phases |
| `LOG_PATH` | `None` | Event log; `None` saves it beside the database |
| `REQUEST_INTERVAL` | `0.25` | Seconds between calls, which is also the minimum |
| `REQUEST_TIMEOUT` | `10.0` | Seconds to wait for each response, up to 60 |
| `MAX_RETRIES` | `2` | Retries of an uncertain request, using the same request ID |
| `ALLOW_UNSAVED_SERVER_PULLS` | `False` | `True` continues even if the server has pulls the database doesn't |

Before pulling, the script compares the server's pull count with the database and stops if they don't match. If someone has already made test pulls, import any saved responses before running this. Only set `ALLOW_UNSAVED_SERVER_PULLS = True` if those responses are lost and the group knows why the counts differ.

## Reading the results

Every run prints a table of all 24 arms. Once each arm has at least 4 pulls, it also prints these checks:

| Check | Normal result (2,400 pulls) | If it's outside that |
|---|---|---|
| Noise | About 1, within 0.06 | Above that, the data is noisier than binomial, so Thompson Sampling will be overconfident |
| Stability, per arm | 0 to 3 of 24 arms moved by more than 2 standard errors | 4 or more suggests the rates aren't stable |
| Stability, all arms together | Between −2 and 2 | Outside that suggests all rates are drifting together |

These checks only cover the pilot. They can't rule out rates changing later, so the main run still needs its own monitoring.

## Next step

Once all 24 arms have 100 pulls:

1. **Review the checks as a group.** If noise or stability looks wrong, reassess the method before making more pulls.
2. **Run the final simulation (no pulls).** Draw plausible rates from the pilot's results, then simulate the remaining 997,600 pulls for each method. The simulator can't read real pilot data yet, so that needs adding.
3. **Build the main run.** It should use the method the simulation supports, expected to be Thompson Sampling, and start from this same database. `program/` has only uniform and UCB so far, and its default UCB setting performed poorly in simulation.

Use the speed printed by the final run to confirm the main run's start date. The full budget takes at least 69 hours, and new pulls close on 15 November 2026 at 23:59 Singapore time.
