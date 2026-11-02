"""Phase 1 settings. Edit this file, then run `python main.py`. Never add the password here."""

# Live pulls
ONLINE = False                  # True enables real, budget-consuming requests
MAX_PULLS_THIS_RUN = 1          # 1 tests the live pull; 2400 then finishes the pilot
PULLS_PER_ARM = 100             # Pilot target; main.py stops when every arm reaches it
GROUP_USERNAME = ""             # Assigned group account; blank means prompt

# Files: relative paths are anchored to this folder. Later phases share this database.
DB_PATH = "../program/data/history.sqlite3"
LOG_PATH = None                 # None -> database name with .online.jsonl suffix

# Request settings
REQUEST_INTERVAL = 0.25         # Seconds between HTTP calls; minimum 0.25
REQUEST_TIMEOUT = 10.0          # Seconds, greater than 0 and at most 60
MAX_RETRIES = 2                 # Uncertain retries reuse the same request identity

# Safety check
ALLOW_UNSAVED_SERVER_PULLS = False  # True only if the group knows why the server is ahead of the database
