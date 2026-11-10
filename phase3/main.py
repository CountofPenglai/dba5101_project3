"""Phase 3 live run: the rest of the budget, using UCB from the saved pilot onward.

First stage: UCB with bonus multiplier 0.05 until the database holds 1,200 pulls, then a recheck.
Run with `python main.py` from this folder. Offline unless config.ONLINE is True.

Phase 1's driver (phase1/main.py) supplies the database lock on Windows, the server check,
safe retries, the progress lines and the error messages. This file changes only the model
(UCB instead of uniform), the stopping rule (a total pull target) and the final report.
"""

import importlib.util
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path

import config  # This folder's settings. Phase 1's helpers read the same names from it.

HERE = Path(__file__).resolve().parent
PILOT_PULLS = 240  # Phase 1 made pulls 0-239, 10 on each arm
SINGAPORE = timezone(timedelta(hours=8))


def load_phase1():
    """Import phase1/main.py as `phase1_main`, so it can't be confused with this file."""
    spec = importlib.util.spec_from_file_location("phase1_main", HERE.parent / "phase1" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # Adds program/ to sys.path and installs the Windows lock
    # Its server check reads REQUEST_INTERVAL, REQUEST_TIMEOUT and ALLOW_UNSAVED_SERVER_PULLS.
    module.config = config
    return module


pilot = load_phase1()

from bandit import UCBModel, run_experiment  # noqa: E402  (importable once phase 1 has set the path)
from bandit.client import validate_settings  # noqa: E402
from bandit.common import ARMS, DEADLINE, MAX_PULLS, SERVER_URL, VISITORS_PER_PULL  # noqa: E402

ConfigError = pilot.ConfigError


class ProgressUCB(pilot.ProgressModel, UCBModel):
    """UCB that prints phase 1's progress line for each live result once it is saved.

    Phase 1's ProgressModel supplies fit, update and the printout. UCBModel supplies the
    arm choice, plus the name and parameters saved with every request.
    """

    def __init__(self, target, exploration):
        UCBModel.__init__(self, exploration)
        self.target, self.live = target, False


def exploration():
    """program/bandit's setting for the bonus multiplier: exploration = 2 x multiplier^2.

    Rounded so that 0.05 gives exactly 0.005, the value saved with each request.
    """
    return round(2 * config.UCB_MULTIPLIER ** 2, 12)


def validate_config():
    pilot.check_whole_number("TARGET_TOTAL_PULLS", 1, MAX_PULLS)
    pilot.check_whole_number("MAX_PULLS_THIS_RUN", 0, MAX_PULLS)
    multiplier = config.UCB_MULTIPLIER
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not 0 < multiplier <= 1:
        raise ConfigError("UCB_MULTIPLIER must be a number above 0 and at most 1.")
    if type(config.MAX_RETRIES) is not int or config.MAX_RETRIES < 0:
        raise ConfigError("MAX_RETRIES must be a whole number, 0 or higher.")
    for name in ("ONLINE", "ALLOW_UNSAVED_SERVER_PULLS"):
        if type(getattr(config, name)) is not bool:
            raise ConfigError("{} must be True or False.".format(name))
    if not isinstance(config.GROUP_USERNAME, str):
        raise ConfigError("GROUP_USERNAME must be text in quotes.")
    try:
        validate_settings(config.REQUEST_INTERVAL, config.REQUEST_TIMEOUT)
    except ValueError:
        raise ConfigError("REQUEST_INTERVAL must be at least 0.25, and REQUEST_TIMEOUT "
                          "must be above 0 and at most 60.") from None


def resolve_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else HERE / path).resolve()


def pulls_left(results):
    return max(0, config.TARGET_TOTAL_PULLS - len(results))


def method_name():
    return "UCB x{:g}, UCBModel(exploration={:g})".format(config.UCB_MULTIPLIER, exploration())


def report(results, completed, elapsed):
    """Every arm ranked by UCB score, what phase 3 has pulled, and the phase 1 checks on all pulls."""
    model = UCBModel(exploration()).fit(results)
    by_arm = pilot.rewards_by_arm(results)
    since = [0] * ARMS
    for row in results:
        if row["Pull"] >= PILOT_PULLS:
            since[int(row["Arm"])] += 1
    scores = {row["arm"]: row["score"] for row in model.summary()}
    next_arm = model.select_arm() if results else None

    print("\n{:>3} {:>6} {:>9} {:>8} {:>10} {:>12}".format(
        "Arm", "Pulls", "Sign-ups", "Rate", "UCB score", "Since pilot"))
    for arm in sorted(range(ARMS), key=lambda a: (-(scores[a] if scores[a] is not None else math.inf), a)):
        rewards = by_arm[arm]
        rate = "{:.2%}".format(sum(rewards) / (VISITORS_PER_PULL * len(rewards))) if rewards else "-"
        score = "{:.4f}".format(scores[arm]) if scores[arm] is not None else "-"
        print("{:>3} {:>6} {:>9} {:>8} {:>10} {:>12}{}".format(
            arm, len(rewards), sum(rewards), rate, score, since[arm],
            "   <- next pull" if arm == next_arm else ""))

    pulls, signups = len(results), sum(row["Reward"] for row in results)
    print("\nTotal saved: {:,} pulls, {:,} sign-ups ({:.2%}). {:,} pulls left before the target of {:,}.".format(
        pulls, signups, signups / (VISITORS_PER_PULL * pulls) if pulls else 0, pulls_left(results),
        config.TARGET_TOTAL_PULLS))
    after = [row for row in results if row["Pull"] >= PILOT_PULLS]
    if after:
        top = max(range(ARMS), key=lambda a: (since[a], -a))
        gained = sum(row["Reward"] for row in after)
        print("Since the pilot: {:,} pulls, {:,} sign-ups ({:.2%}). Arm {} got {:,} of them ({:.1%}).".format(
            len(after), gained, gained / (VISITORS_PER_PULL * len(after)), top, since[top],
            since[top] / len(after)))
    if next_arm is not None:
        print("Next pull with {}: arm {}.".format(method_name(), next_arm))
    if completed and elapsed > 0:
        speed = completed / elapsed
        hours_left = (DEADLINE - datetime.now(timezone.utc)).total_seconds() / 3600
        print("Speed: {:.2f} pulls per second. The {:,} pulls left in the budget would take {:.0f} hours; "
              "new pulls close in {:.0f} hours ({} Singapore time).".format(
                  speed, MAX_PULLS - pulls, (MAX_PULLS - pulls) / speed / 3600, hours_left,
                  DEADLINE.astimezone(SINGAPORE).strftime("%d %B %Y, %H:%M")))

    # Phase 1's noise and stability checks, now over every saved pull.
    ratio, df = pilot.noise_ratio(by_arm)
    scores_moved, overall = pilot.stability(by_arm)
    if ratio is None or not scores_moved:
        print("Noise and stability checks need at least 4 pulls per arm.")
        return
    print("Noise: variance is {:.2f} times binomial (about 1 +/- {:.2f} is normal).".format(
        ratio, 2 * math.sqrt(2 / df)))
    print("Stability: {} of {} arms moved by more than 2 standard errors (0 to 3 is normal). "
          "Largest move: {:.1f}. All arms together: {:.1f}.".format(
              sum(abs(score) > 2 for score in scores_moved), len(scores_moved),
              max(abs(score) for score in scores_moved), overall))


def main():
    password, db_path = None, None
    seen = {"status": None}
    try:
        validate_config()
        db_path = resolve_path(config.DB_PATH)
        log_path = resolve_path(config.LOG_PATH) if config.LOG_PATH is not None else None
        results, pending = pilot.saved_state(db_path)
        left = pulls_left(results)
        allowed = min(config.MAX_PULLS_THIS_RUN, left)
        budget = allowed if config.ONLINE else 0
        print("Method: {}. Saved: {:,} pulls. Target: {:,} ({:,} left).".format(
            method_name(), len(results), config.TARGET_TOTAL_PULLS, left))
        print("Mode: {}. Pulls planned this run: {:,}{}.".format(
            "ONLINE" if config.ONLINE else "OFFLINE", budget,
            "" if config.ONLINE else " (online it would be {:,})".format(allowed)))

        completed, elapsed, stop_reason = 0, 0.0, None
        if budget > 0:
            username = config.GROUP_USERNAME.strip() or input("Group username: ").strip()
            if not username:
                raise ConfigError("A group username is required. Enter one or set GROUP_USERNAME.")
            password = os.environ.get("GP3_PASSWORD") or getpass("Group password: ")
            with pilot.record_http_status(seen), pilot.console_log(seen):
                if not pilot.server_matches_history(username, password, len(results), pending):
                    return 1
                if pending:
                    print("Arm {} has an unfinished request from an earlier run. Retrying it first; "
                          "it counts as one of this run's pulls.".format(pending["arm"]))
                started = time.monotonic()
                model = ProgressUCB(config.TARGET_TOTAL_PULLS, exploration())
                summary = run_experiment(model, budget, online=True, db_path=db_path,
                                         username=username, password=password, server_url=SERVER_URL,
                                         interval=config.REQUEST_INTERVAL, timeout=config.REQUEST_TIMEOUT,
                                         max_retries=config.MAX_RETRIES, log_path=log_path)
            completed, elapsed = summary["completed_pulls"], time.monotonic() - started
            stop_reason = summary["stop_reason"]
            print("Completed {:,} pulls. Stop reason: {}.".format(completed, stop_reason))
            results, pending = pilot.saved_state(db_path)

        if stop_reason in pilot.STOP_MESSAGES:
            print("Run stopped: {}".format(pilot.STOP_MESSAGES[stop_reason]), file=sys.stderr)
        if pending:
            print("A request is still pending for arm {}. Rerun online to recover it.".format(pending["arm"]))
        report(results, completed, elapsed)
        print("\nDatabase:", db_path)
        return 1 if stop_reason in pilot.STOP_MESSAGES else 0
    except KeyboardInterrupt:
        print("Interrupted. Run the same command again to continue.", file=sys.stderr)
        pilot.print_saved_state(db_path)
        return 130
    except Exception as error:
        what, action = pilot.describe_failure(error, seen["status"])
        print("Run stopped: {}\nWhat to do: {}".format(what, action), file=sys.stderr)
        pilot.print_saved_state(db_path)
        return 1
    finally:
        password = None


if __name__ == "__main__":
    raise SystemExit(main())
