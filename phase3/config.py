"""Phase 3 settings. Edit this file, then run `python main.py`. Never add the password here."""

# Method: UCB pulls the arm with the highest mean + UCB_MULTIPLIER x sqrt(2 ln t / n).
# Phase 2's choice is 0.05, which is program/bandit's UCBModel(exploration=0.005).
UCB_MULTIPLIER = 0.05

# Live pulls
ONLINE = False                  # True enables real, budget-consuming requests
TARGET_TOTAL_PULLS = None       # None -> server group cap (1,000,000 total)
MAX_PULLS_THIS_RUN = None       # None -> all remaining; integer -> additional pull cap
GROUP_USERNAME = "group19"      # Assigned group account; blank means prompt

# Files: relative paths are anchored to this folder. Every phase shares this database.
DB_PATH = "../program/data/history.sqlite3"
LOG_PATH = None                 # None -> database name with .online.jsonl suffix

# Request settings
REQUEST_INTERVAL = 0.25         # Seconds between HTTP calls; minimum 0.25
REQUEST_TIMEOUT = 10.0          # Seconds, greater than 0 and at most 60
MAX_RETRIES = None              # None -> retry uncertain requests until stopped; capped backoff
PROGRESS_EVERY = 1000           # Do not accumulate/print every response

# Optional local tuning. Disabling it keeps UCB_MULTIPLIER fixed.
AUTO_TUNE = False
TUNE_EVERY = 200000
TUNE_CANDIDATES = (0.02, 0.03, 0.05, 0.075, 0.10)
TUNE_TRAIN_WORLDS = 96
TUNE_VALIDATION_WORLDS = 384
TUNE_MAX_SECONDS = 600.0        # Timeout retains current parameters
TUNE_CVAR_LEVEL = 0.95          # Mean loss in the worst 5% posterior scenarios
TUNE_STAGE_LOSS_ALLOWANCE = 0.0 # Extra stage regret versus baseline, in sign-ups
TUNE_TAIL_LOSS_ALLOWANCE = 0.0  # Extra CVaR versus baseline, in sign-ups

# Safety check
ALLOW_UNSAVED_SERVER_PULLS = False  # True only if the group knows why the server is ahead of the database
