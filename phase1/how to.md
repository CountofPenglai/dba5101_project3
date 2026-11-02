# How to Run Phase 1

Edit `config.py`, then run `python main.py` from this folder.

## Settings

| Setting | Meaning |
|---|---|
| `ONLINE` | `True` makes real pulls; `False` makes none |
| `MAX_PULLS_THIS_RUN` | Most pulls per run |
| `PULLS_PER_ARM` | Target pulls for each arm |
| `GROUP_USERNAME` | Group account; blank means it asks |
| `DB_PATH` | Where results are saved |
| `LOG_PATH` | Where events are logged; `None` means beside the database |
| `REQUEST_INTERVAL` | Seconds between calls |
| `REQUEST_TIMEOUT` | Seconds to wait for a response |
| `MAX_RETRIES` | Retries of an uncertain request |
| `ALLOW_UNSAVED_SERVER_PULLS` | `True` continues if the server has pulls the database doesn't |

## How the code runs

1. Reads the settings and saved results, and works out how many pulls are left.
2. If `ONLINE` is `True`, asks for the password and checks the server's pull count against the database.
3. Pulls the least-pulled arm, saving each result, until it reaches the run limit or every arm reaches its target.
4. Prints each arm's results and the checks.

## Order of runs

1. `ONLINE = False`: check the setup.
2. `ONLINE = True`, `MAX_PULLS_THIS_RUN = 1`: test one live pull.
3. `MAX_PULLS_THIS_RUN = 2400`: finish the pilot.
