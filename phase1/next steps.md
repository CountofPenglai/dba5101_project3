# Next Steps After the Pilot

Start here once `main.py` prints `0 pulls left in this phase`, meaning all 24 arms have 100 pulls.

## Pulls left

| | Pulls |
|---|---|
| Group budget | 1,000,000 |
| Used by the pilot | 2,400 |
| **Left for the main run** | **997,600** |

This assumes nobody else has used the account, because any test pulls also count. To confirm, call `status(username, password)` from `program/server_pull.py`, which uses no pulls. `PullsUsed` should be 2,400, and `NetReward` should match the total sign-ups printed by `main.py`.

## What to do

1. **Stop and back up.** Set `ONLINE = False` in `config.py`. Copy `history.sqlite3` and `history.online.jsonl` from `program/data/` somewhere private to the group.

2. **Review the checks together.** Compare the noise and stability results with the table in `README.md`. If either looks wrong, make no more pulls until the group has reassessed the method.

3. **Set the start date.** Use the speed printed by the final pilot run to work out how long 997,600 pulls will take. The minimum is about 69 hours, and at 2 pulls per second it's about 139 hours (roughly 6 days). New pulls close on 15 November 2026 at 23:59 Singapore time, and the report still has to be written after the run.

4. **Run the final simulation (no pulls).** `offline_simulation/simulate.py` can't read real pilot data yet, so that needs adding first.
   - Draw plausible rates from the pilot's uncertainty, not its averages. Using the averages unfairly favoured explore-first in earlier simulations.
   - Simulate the remaining 997,600 pulls for each method.
   - Use Thompson Sampling unless the pilot shows unstable rates or the simulation clearly favours another method.

5. **Build the main-run driver.** `program/` needs these changes first:
   - **Add the method:** it has no Thompson Sampling yet.
   - **Fix the UCB setting if using UCB:** the default `UCB_EXPLORATION = 2.0` lost about 900,000–1,160,000 sign-ups in simulation. The better version corresponds to about `0.005`.
   - **Add Windows support if running on Windows:** `program/` only runs on macOS/Linux. `phase1/main.py` has a Windows file lock that can be reused.
   - **Start from the pilot's data:** use the same database so the pilot's pulls aren't wasted.
   - **Test before going live:** use a fake server, including failed requests.

6. **Run the main experiment.**
   - Have one person run it on a computer that can stay on and connected for days.
   - Keep at least 0.25 seconds between calls.
   - Use the full budget, since every pull can add sign-ups.
   - Compare the leading arm's recent average with its earlier average. If it shifts clearly, pause and reassess. The pilot can't rule out rates changing later on.

7. **Write the report and submit.**
   - Report pull usage, total sign-ups, the chosen arm and your confidence in it using live results only. Label any simulation figures as simulated.
   - Submit a report PDF of at most 4 pages and an HTML export of the code, including any LLM prompts used.
   - Export with `jupyter nbconvert --to html`, without `--execute`, so no live cells run again.
   - Make sure the group password doesn't appear in either file.
