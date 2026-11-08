"""Phase 2 settings. Edit this file, then run `python main.py`.

Phase 2 is offline: it makes no pulls and opens the database read-only.
"""

# Data: the pilot pulls saved by phase 1. Relative paths are anchored to this folder.
DB_PATH = "../program/data/history.sqlite3"
RESULTS_DIR = "results"         # CSVs are written here; each run overwrites them

# Beta prior for each arm's conversion rate: Beta(1, 1) is uniform on 0-100%.
# Posterior = Beta(PRIOR_A + sign-ups, PRIOR_B + non-sign-ups).
PRIOR_A = 1.0
PRIOR_B = 1.0

# The combinations: each uniform total x (every UCB multiplier, every epsilon, and Thompson Sampling).
# The original plan's 40 used multipliers 0.05-1; 0.005-0.02 were added after 0.05 won at the edge.
UNIFORM_TOTALS = [10, 25, 50, 100]          # Pulls per arm, real pilot included, before the method takes over
UCB_MULTIPLIERS = [0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1]  # Bonus = multiplier x sqrt(2 ln t / n)
EPSILONS = [0.01, 0.025, 0.05, 0.1, 0.2]    # Chance of pulling a random arm instead of the leader
THOMPSON = True                 # Also simulate Thompson Sampling (no parameter to tune) at each uniform total

# Simulation size
TOTAL_PULLS = 1_000_000         # Whole budget, real pulls included. Lower it if time runs short
REPS = 200                      # Simulated worlds, shared by all 40 combinations
VALIDATE_TOP = 5                # This many leading combinations are rerun on fresh worlds
VALIDATE_REPS = 200             # Worlds in that rerun
SEED = 5101                     # Same seed and settings give the same results
WORKERS = None                  # Parallel processes; None means CPU count minus 1
