"""Phase 3 settings. Edit this file, then run `python main.py`. Never add the password here."""

# Method: UCB pulls the arm with the highest mean + UCB_MULTIPLIER x sqrt(2 ln t / n).
# Phase 2's choice is 0.05, which is program/bandit's UCBModel(exploration=0.005).
UCB_MULTIPLIER = 0.05

# Live pulls
ONLINE = False                  # True enables real, budget-consuming requests
TARGET_TOTAL_PULLS = 1200       # Stop when the database holds this many pulls, the pilot's 240 included
MAX_PULLS_THIS_RUN = 1200          # Upper limit for each run: 1 for the live test, then 960
GROUP_USERNAME = "group19"      # Assigned group account; blank means prompt

# Files: relative paths are anchored to this folder. Every phase shares this database.
DB_PATH = "../program/data/history.sqlite3"
LOG_PATH = None                 # None -> database name with .online.jsonl suffix

# Request settings
REQUEST_INTERVAL = 0.25         # Seconds between HTTP calls; minimum 0.25
REQUEST_TIMEOUT = 10.0          # Seconds, greater than 0 and at most 60
MAX_RETRIES = 2                 # Uncertain retries reuse the same request identity

# Safety check
ALLOW_UNSAVED_SERVER_PULLS = False  # True only if the group knows why the server is ahead of the database
