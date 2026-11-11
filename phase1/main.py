"""Phase 1 live pilot: balanced real pulls across all arms, then noise and stability checks.

Run with `python main.py` from this folder. Offline unless config.ONLINE is True.
"""

import http.client
import math
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from functools import partial
from getpass import getpass
from pathlib import Path
from statistics import mean, variance

import config

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "program"))

import server_pull
from bandit import HistoryStore, UniformModel, run_experiment, runner
from bandit.audit import OnlineLog
from bandit.client import PacedClient, validate_settings
from bandit.common import ARMS, MAX_PULLS, SERVER_URL, VISITORS_PER_PULL, integer

# Safety limits, not settings: config.py can't go above these.
PULLS_PER_ARM_LIMIT = 200
PULLS_THIS_RUN_LIMIT = 4800

HTTP_FAILURES = {
    400: ("The server rejected the request as invalid (HTTP 400).",
          "Don't change the database. Contact the teaching team."),
    401: ("The server rejected the username or password (HTTP 401).",
          "Check GROUP_USERNAME and retype the password. If GP3_PASSWORD is set, clear or correct it."),
    403: ("The server refused access (HTTP 403). The account may lack access, or the experiment may be closed.",
          "Check the account, then contact the teaching team if it looks correct."),
    409: ("The server's pull counter doesn't match this request (HTTP 409). "
          "Someone else may have used the account.",
          "Make sure nobody else is pulling. Don't change the database. Contact the teaching team."),
    429: ("The server is rate-limiting requests (HTTP 429).",
          "Wait a minute, then run the same command again. Any unfinished request is retried safely."),
}
STOP_MESSAGES = {
    "server_closed": "The server is closed to new pulls.",
    "group_budget_exhausted": "The group has used all of its pulls.",
    "deadline_reached": "The project deadline has passed, so no new pulls can start.",
}


class ConfigError(ValueError):
    """A setting in config.py is outside what this phase allows."""


class ProgressModel(UniformModel):
    """Uniform selection that prints each live result and running totals once it is saved."""

    def __init__(self, target):
        super().__init__()
        self.target = target
        self.live = False

    def fit(self, results):
        self.live = False  # Replaying saved history isn't new progress.
        super().fit(results)
        self.live = True
        return self

    def update(self, result):
        super().update(result)
        if self.live:
            self.print_progress(result)

    def fit_aggregates(self, rows):
        self.live = False
        super().fit_aggregates(rows)
        self.live = True
        return self

    def print_progress(self, result):
        arm = int(result["Arm"])
        rates = {i: self.signups[i] / (VISITORS_PER_PULL * self.counts[i])
                 for i in range(ARMS) if self.counts[i]}
        high, low = max(rates, key=rates.get), min(rates, key=rates.get)
        total = sum(self.signups)
        print("Result:", result, flush=True)
        print("  Saved {}/{} ({:.1%}) | arm {}: {} sign-ups, {:.2%} over {} pulls | "
              "total {} ({:.2%}), server NetReward {} | highest arm {} {:.2%} | lowest arm {} {:.2%}".format(
                  self.total_pulls, self.target, self.total_pulls / self.target, arm, result["Reward"],
                  rates[arm], self.counts[arm], total, total / (VISITORS_PER_PULL * self.total_pulls),
                  result["NetReward"], high, rates[high], low, rates[low]), flush=True)


class ConsoleLog(OnlineLog):
    """The runner's event log, which also prints retries of an uncertain request."""

    def __init__(self, path, run_id, seen):
        super().__init__(path, run_id)
        self.seen = seen
        self.attempts = None

    def write(self, event, **fields):
        super().write(event, **fields)
        attempt, arm = fields.get("attempt"), (fields.get("request") or {}).get("arm")
        if event == "run_started":
            self.attempts = fields["max_retries"] + 1 if fields['max_retries'] is not None else 'unlimited'
        elif event == "pull_uncertain":
            print("Arm {}: no reliable response on attempt {} of {} ({}). {}".format(
                arm, attempt, self.attempts, uncertain_reason(self.seen["status"]),
                "Retrying the same request." if fields["retry_scheduled"] else "No retries left."), flush=True)
        elif event == "pull_completed" and attempt > 1:
            print("Arm {}: response received on attempt {}. It was the same request, so it counts "
                  "as one pull.".format(arm, attempt), flush=True)


def uncertain_reason(status):
    """Why a pull response couldn't be trusted, from the last HTTP status seen."""
    if status is None:
        return "timed out or the connection dropped"
    if status == 429:
        return "rate-limited, HTTP 429"
    if status >= 500:
        return "server error or still waking up, HTTP {}".format(status)
    if status == 200:
        return "the response wasn't valid"
    return "HTTP {}".format(status)


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


def check_whole_number(name, minimum, maximum):
    value = getattr(config, name)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigError("{} must be a whole number from {} to {}.".format(name, minimum, maximum))


def validate_config():
    check_whole_number("PULLS_PER_ARM", 1, PULLS_PER_ARM_LIMIT)
    check_whole_number("MAX_PULLS_THIS_RUN", 0, PULLS_THIS_RUN_LIMIT)
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


@contextmanager
def record_http_status(seen):
    """Note each HTTP status code, which server_pull hides from its callers. Nothing else is kept."""
    original = server_pull._request

    def request(*args, **kwargs):
        seen["status"] = None
        code, data = original(*args, **kwargs)
        seen["status"] = code
        return code, data

    server_pull._request = request
    try:
        yield
    finally:
        server_pull._request = original


@contextmanager
def console_log(seen):
    """Have the runner's event log also print retries to the console."""
    original = runner.OnlineLog
    runner.OnlineLog = partial(ConsoleLog, seen=seen)
    try:
        yield
    finally:
        runner.OnlineLog = original


def describe_failure(error, status):
    """Return what happened and what to do. Never echoes server text, which can be arbitrary."""
    retry = "Run the same command again. Any unfinished request is retried safely."
    if isinstance(error, ConfigError):
        return str(error), "Fix config.py, then run again."
    if status in HTTP_FAILURES:
        return HTTP_FAILURES[status]
    if status is not None and status >= 500:
        return ("The server had a problem or is still waking up (HTTP {}).".format(status),
                "Wait a few minutes. " + retry)
    if isinstance(error, server_pull.UncertainPullError):
        if status == 200:
            return "The server replied, but its response wasn't valid.", "Contact the teaching team if this repeats."
        return "No reliable response arrived, even after retries.", "Check your connection. " + retry
    if isinstance(error, (ConnectionError, TimeoutError, http.client.HTTPException)):
        return ("Couldn't get a response from the server. It may be waking up, or the connection dropped.",
                "Check your connection and wait a minute. " + retry)
    if isinstance(error, sqlite3.Error):
        return ("Couldn't read or write the database ({}).".format(type(error).__name__),
                "Close anything else using it and check the disk, then run again. Don't delete the database.")
    if isinstance(error, OSError):
        return "Couldn't use a local file: {}".format(error), "Check DB_PATH, LOG_PATH and the disk, then run again."
    if isinstance(error, EOFError):
        return "Couldn't read the username or password.", "Run this in PowerShell, cmd or Windows Terminal."
    if isinstance(error, (RuntimeError, ValueError)):
        # HTTP rejections were handled above, so these messages come from local code.
        message = str(error)
        if "Another driver" in message:
            return message + ".", "Let the other run finish or close it, then run again."
        if "belongs to another group" in message:
            return message + ".", "Use the group account this database was started with."
        return message + ".", "Check config.py. Contact the teaching team if this repeats."
    return "Unexpected error ({}).".format(type(error).__name__), "Contact whoever maintains this script."


def print_saved_state(db_path):
    if db_path is None:
        return
    try:
        results, pending = saved_state(db_path)
    except Exception:
        return  # The failure above already explains why the database can't be read.
    print("Saved so far: {} pulls.".format(len(results)), file=sys.stderr)
    if pending:
        print("Arm {} has an unfinished request. The next online run retries it first.".format(pending["arm"]),
              file=sys.stderr)


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
    password, db_path = None, None
    seen = {"status": None}
    try:
        validate_config()
        db_path = resolve_path(config.DB_PATH)
        log_path = resolve_path(config.LOG_PATH) if config.LOG_PATH is not None else None
        results, pending = saved_state(db_path)
        by_arm = rewards_by_arm(results)
        # Uniform always picks the least-pulled arm, so these pulls only fill arms below target.
        budget = min(config.MAX_PULLS_THIS_RUN, remaining_pulls(by_arm)) if config.ONLINE else 0
        print("Mode: {}. Pulls planned this run: {}.".format("ONLINE" if config.ONLINE else "OFFLINE", budget))

        completed, elapsed, stop_reason = 0, 0.0, None
        if budget > 0:
            username = config.GROUP_USERNAME.strip() or input("Group username: ").strip()
            if not username:
                raise ConfigError("A group username is required. Enter one or set GROUP_USERNAME.")
            password = os.environ.get("GP3_PASSWORD") or getpass("Group password: ")
            with record_http_status(seen), console_log(seen):
                if not server_matches_history(username, password, len(results), pending):
                    return 1
                if pending:
                    print("Arm {} has an unfinished request from an earlier run. Retrying it first; "
                          "it counts as one of this run's pulls.".format(pending["arm"]))
                started = time.monotonic()
                model = ProgressModel(len(results) + remaining_pulls(by_arm))
                summary = run_experiment(model, budget, online=True, db_path=db_path,
                                         username=username, password=password, server_url=SERVER_URL,
                                         interval=config.REQUEST_INTERVAL, timeout=config.REQUEST_TIMEOUT,
                                         max_retries=config.MAX_RETRIES, log_path=log_path)
            completed, elapsed = summary["completed_pulls"], time.monotonic() - started
            stop_reason = summary["stop_reason"]
            print("Completed {} pulls. Stop reason: {}.".format(completed, stop_reason))
            results, pending = saved_state(db_path)

        if stop_reason in STOP_MESSAGES:
            print("Run stopped: {}".format(STOP_MESSAGES[stop_reason]), file=sys.stderr)
        if pending:
            print("A request is still pending for arm {}. Rerun online to recover it.".format(pending["arm"]))
        report(rewards_by_arm(results), completed, elapsed)
        print("\nDatabase:", db_path)
        return 1 if stop_reason in STOP_MESSAGES else 0
    except KeyboardInterrupt:
        print("Interrupted. Run the same command again to continue.", file=sys.stderr)
        print_saved_state(db_path)
        return 130
    except Exception as error:
        what, action = describe_failure(error, seen["status"])
        print("Run stopped: {}\nWhat to do: {}".format(what, action), file=sys.stderr)
        print_saved_state(db_path)
        return 1
    finally:
        password = None


if __name__ == "__main__":
    raise SystemExit(main())
