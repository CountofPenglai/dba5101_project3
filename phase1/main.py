"""Phase 1 live pilot: balanced real pulls across all arms, then noise and stability checks.

Run with `python main.py` from this folder. Offline unless config.ONLINE is True.
"""

import math
import os
import sys
import time
from contextlib import contextmanager
from getpass import getpass
from pathlib import Path
from statistics import mean, variance

import config

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "program"))

from bandit import HistoryStore, UniformModel, run_experiment, runner
from bandit.client import PacedClient, validate_settings
from bandit.common import ARMS, MAX_PULLS, SERVER_URL, VISITORS_PER_PULL, integer


@contextmanager
def windows_lock(path):
    """Windows version of bandit.storage.driver_lock, which needs fcntl (macOS/Linux only)."""
    import msvcrt

    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("Another driver is using this database") from None
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


if sys.platform == "win32":
    runner.driver_lock = windows_lock


def resolve_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else HERE / path).resolve()


def validate_config():
    integer(config.PULLS_PER_ARM, "PULLS_PER_ARM", minimum=1, maximum=MAX_PULLS // ARMS)
    integer(config.MAX_PULLS_THIS_RUN, "MAX_PULLS_THIS_RUN")
    integer(config.MAX_RETRIES, "MAX_RETRIES")
    for name in ("ONLINE", "ALLOW_UNSAVED_SERVER_PULLS"):
        if type(getattr(config, name)) is not bool:
            raise ValueError("{} must be True or False".format(name))
    if not isinstance(config.GROUP_USERNAME, str):
        raise ValueError("GROUP_USERNAME must be a string")
    validate_settings(config.REQUEST_INTERVAL, config.REQUEST_TIMEOUT)


def saved_state(db_path):
    with runner.driver_lock(db_path), HistoryStore(db_path) as store:
        return list(store.results()), store.pending


def rewards_by_arm(results):
    by_arm = [[] for _ in range(ARMS)]
    for row in results:
        by_arm[int(row["Arm"])].append(row["Reward"])
    return by_arm


def remaining_pulls(by_arm):
    return sum(max(0, config.PULLS_PER_ARM - len(rewards)) for rewards in by_arm)


def server_matches_history(username, password, local_pulls, pending):
    """Compare the account with saved history before any pull. Status uses no budget."""
    with PacedClient(username, password, SERVER_URL, interval=config.REQUEST_INTERVAL,
                     timeout=config.REQUEST_TIMEOUT) as client:
        used = integer(client.status().get("PullsUsed"), "server PullsUsed", maximum=MAX_PULLS)
    print("Server pulls used: {}. Saved locally: {}.".format(used, local_pulls))
    # A pending request may already be recorded on the server but not yet saved here.
    if used < local_pulls:
        print("Stopped: saved history is ahead of the server. Check the group and database.")
        return False
    if used > local_pulls + bool(pending) and not config.ALLOW_UNSAVED_SERVER_PULLS:
        print("Stopped: the server has pulls this database does not. Find out who made them "
              "and import any saved responses. No pulls were made.")
        return False
    return True


def noise_ratio(by_arm):
    """Observed batch variance over the binomial variance; about 1 if batches are binomial."""
    observed, expected, df = 0.0, 0.0, 0
    for rewards in by_arm:
        if len(rewards) >= 2:
            rate = mean(rewards) / VISITORS_PER_PULL
            observed += (len(rewards) - 1) * variance(rewards)
            expected += (len(rewards) - 1) * VISITORS_PER_PULL * rate * (1 - rate)
            df += len(rewards) - 1
    return (observed / expected, df) if expected else (None, 0)


def stability(by_arm):
    """Standardized change from each arm's first half of pulls to its last half."""
    scores, shift, spread = [], 0.0, 0.0
    for rewards in by_arm:
        half = len(rewards) // 2
        rate = mean(rewards) / VISITORS_PER_PULL if rewards else 0
        if half >= 2 and 0 < rate < 1:
            change = mean(rewards[-half:]) - mean(rewards[:half])
            error = 2 * VISITORS_PER_PULL * rate * (1 - rate) / half
            scores.append(change / math.sqrt(error))
            shift += change
            spread += error
    return scores, (shift / math.sqrt(spread) if spread else None)


def report(by_arm, completed, elapsed):
    print("\n{:>3} {:>6} {:>9} {:>10}".format("Arm", "Pulls", "Sign-ups", "Rate"))
    for arm, rewards in enumerate(by_arm):
        rate = "{:.2%}".format(mean(rewards) / VISITORS_PER_PULL) if rewards else "-"
        print("{:>3} {:>6} {:>9} {:>10}".format(arm, len(rewards), sum(rewards), rate))

    pulls = sum(len(rewards) for rewards in by_arm)
    print("\nTotal saved: {} pulls, {} sign-ups. {} pulls left in this phase.".format(
        pulls, sum(sum(rewards) for rewards in by_arm), remaining_pulls(by_arm)))
    if completed and elapsed > 0:
        speed = completed / elapsed
        print("Speed: {:.2f} pulls per second. The rest of the budget would take {:.0f} hours.".format(
            speed, (MAX_PULLS - pulls) / speed / 3600))

    ratio, df = noise_ratio(by_arm)
    scores, overall = stability(by_arm)
    if ratio is None or not scores:
        print("Noise and stability checks need at least 4 pulls per arm.")
        return
    print("Noise: variance is {:.2f} times binomial (about 1 +/- {:.2f} is normal).".format(
        ratio, 2 * math.sqrt(2 / df)))
    print("Stability: {} of {} arms moved by more than 2 standard errors (0 to 3 is normal). "
          "Largest move: {:.1f}. All arms together: {:.1f}.".format(
              sum(abs(score) > 2 for score in scores), len(scores),
              max(abs(score) for score in scores), overall))


def main():
    password = None
    try:
        validate_config()
        db_path = resolve_path(config.DB_PATH)
        log_path = resolve_path(config.LOG_PATH) if config.LOG_PATH is not None else None
        results, pending = saved_state(db_path)
        by_arm = rewards_by_arm(results)
        # Uniform always picks the least-pulled arm, so these pulls only fill arms below target.
        budget = min(config.MAX_PULLS_THIS_RUN, remaining_pulls(by_arm)) if config.ONLINE else 0
        print("Mode: {}. Pulls planned this run: {}.".format("ONLINE" if config.ONLINE else "OFFLINE", budget))

        completed, elapsed = 0, 0.0
        if budget > 0:
            username = config.GROUP_USERNAME.strip() or input("Group username: ").strip()
            if not username:
                raise ValueError("A group username is required")
            password = os.environ.get("GP3_PASSWORD") or getpass("Group password: ")
            if not server_matches_history(username, password, len(results), pending):
                return 1
            started = time.monotonic()
            summary = run_experiment(UniformModel(), budget, online=True, db_path=db_path,
                                     username=username, password=password, server_url=SERVER_URL,
                                     interval=config.REQUEST_INTERVAL, timeout=config.REQUEST_TIMEOUT,
                                     max_retries=config.MAX_RETRIES, log_path=log_path)
            completed, elapsed = summary["completed_pulls"], time.monotonic() - started
            print("Completed {} pulls. Stop reason: {}.".format(completed, summary["stop_reason"]))
            results, pending = saved_state(db_path)

        if pending:
            print("A request is still pending for arm {}. Rerun online to recover it.".format(pending["arm"]))
        report(rewards_by_arm(results), completed, elapsed)
        print("\nDatabase:", db_path)
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Saved results and pending request state are retained. Rerun to continue.",
              file=sys.stderr)
        return 130
    except Exception as error:
        # A remote RuntimeError can contain arbitrary server text; do not echo it.
        print("Run stopped ({}). Check config.py and the local log; "
              "saved results and pending request state are retained.".format(type(error).__name__),
              file=sys.stderr)
        return 1
    finally:
        password = None


if __name__ == "__main__":
    raise SystemExit(main())
