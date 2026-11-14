"""Check the current or latest run on demand. Read-only: it never pulls and never writes.

Run from this folder, in a second terminal while main.py is pulling:
    python checklocalstatus.py              the latest run, with the last 10 pulls
    python checklocalstatus.py --last 25    show more of the latest pulls
    python checklocalstatus.py --watch 30   refresh every 30 seconds; Ctrl-C to stop

Sources, both opened read-only:
  - the event log: per-pull timing, retries and tuning, from its last few MB only
  - the database: totals, pending request, and the pulls per arm in this run
"""

import argparse
import json
import math
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "program"))
from bandit.common import DEADLINE, MAX_PULLS, VISITORS_PER_PULL as V  # noqa: E402

SGT = timezone(timedelta(hours=8))
TAIL_BYTES = 8_000_000  # About 8,000 recent pulls of the event log; enough for timing stats


def resolve(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else HERE / path).resolve()


def sgt(moment):
    return moment.astimezone(SGT).strftime("%d %b %H:%M:%S")


def duration(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "{}h {:02d}m {:02d}s".format(hours, minutes, secs) if hours else "{}m {:02d}s".format(minutes, secs)


def percentile(sorted_values, q):
    if not sorted_values:
        return float("nan")
    index = min(len(sorted_values) - 1, max(0, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[index]


def spread(values):
    """Mean, standard deviation and percentiles of a list of seconds."""
    values = sorted(values)
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1)) if len(values) > 1 else 0.0
    return {"n": len(values), "mean": mean, "sd": sd, "min": values[0], "p50": percentile(values, .5),
            "p90": percentile(values, .9), "p99": percentile(values, .99), "max": values[-1]}


def tail_events(log_path):
    """Parsed events from the end of the log, starting at the newest run_started if it is in range."""
    size = log_path.stat().st_size
    with open(log_path, "rb") as handle:
        handle.seek(max(0, size - TAIL_BYTES))
        data = handle.read()
    lines = data.split(b"\n")
    if size > TAIL_BYTES:
        lines = lines[1:]  # The first line is cut part-way through
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            pass  # Blank, or the line the driver is still writing
    starts = [i for i, e in enumerate(events) if e.get("event") == "run_started"]
    if starts:
        return events[starts[-1]:], events[starts[-1]]
    return events, find_run_start(log_path)


def find_run_start(log_path):
    """The newest run_started further back than the tail. Streams the file; slow only for huge logs."""
    found = None
    with open(log_path, "rb") as handle:
        for line in handle:
            if b'"run_started"' in line:
                found = line
    return json.loads(found) if found else None


def hours_minutes(seconds):
    minutes = int(round(max(0, seconds) / 60))
    return "{}h {:02d}m".format(*divmod(minutes, 60))


def completion(state, events, start_pull, budget, speed, now, finished):
    """Time left at the recent speed, including tuning checks still due, and the predicted finish."""
    if finished:
        end, title = MAX_PULLS, "If the rest of the budget ran from now at {:.2f} pulls/s:".format(speed)
    else:
        end = min(MAX_PULLS, start_pull + budget) if isinstance(budget, int) else MAX_PULLS
        title = "Time to complete this run, at the recent {:.2f} pulls/s:".format(speed)
    left = max(0, end - state["pulls"])
    pulling = left / speed

    # Tuning checks pause pulling. Assume tuning stays on if it has ever been used.
    decisions = [json.loads(payload) for _, payload in state["decisions"]]
    tuning = [e for e in events if e.get("event") in ("tuning_started", "tuning_completed")]
    running_check = bool(tuning) and tuning[-1]["event"] == "tuning_started"
    checks, each, measured = 0, 382.0, False  # 382 s: the offline preview on 11 Nov
    if decisions or running_check:
        lengths, began = [], None
        for e in tuning:
            moment = datetime.fromisoformat(e["timestamp"])
            if e["event"] == "tuning_started":
                began = moment
            elif began is not None:
                lengths.append((moment - began).total_seconds())
                began = None
        if lengths:
            each, measured = sum(lengths) / len(lengths), True
        last = decisions[-1] if decisions else None
        step = (last["next_at"] - last["at_pull"]) if last else config.TUNE_EVERY
        due = last["next_at"] if last else state["pulls"]
        while due < end:
            checks += 1
            due += step
    pause = checks * each
    total = pulling + pause
    finish = now + timedelta(seconds=total)
    spare = (DEADLINE - finish).total_seconds()

    print("\n" + title)
    print("  Pulls left: {:,}, up to {:,} saved -> about {}".format(left, end, hours_minutes(pulling)))
    if checks:
        print("  Tuning checks still due: {} x about {} ({}) -> about {}".format(
            checks, duration(each), "measured" if measured else "estimate from the preview", hours_minutes(pause)))
    print("  Time left: about {}. Predicted finish: {} Singapore time".format(hours_minutes(total), sgt(finish)))
    if spare >= 0:
        print("  That is {} before pulls close ({}).".format(hours_minutes(spare), sgt(DEADLINE)))
    else:
        print("  That is AFTER pulls close ({}): about {:,} pulls would be left unmade.".format(
            sgt(DEADLINE), int(-spare * speed)))


def database_state(db_path, run_start_pull):
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        db.execute("BEGIN")  # One consistent snapshot, held for milliseconds
        pulls, last, net = db.execute("SELECT COUNT(*), MAX(pull), MAX(net_reward) FROM results").fetchone()
        pending = db.execute("SELECT payload FROM pending WHERE singleton=1").fetchone()
        overall = db.execute("SELECT arm, COUNT(*), SUM(reward) FROM results GROUP BY arm").fetchall()
        this_run = db.execute("SELECT arm, COUNT(*), SUM(reward) FROM results WHERE pull >= ? GROUP BY arm",
                              (run_start_pull,)).fetchall()
        try:
            decisions = db.execute("SELECT at_pull, payload FROM tuning_decisions ORDER BY id").fetchall()
        except sqlite3.OperationalError:
            decisions = []
    return {"pulls": pulls, "last_pull": last, "signups": net or 0,
            "pending": json.loads(pending[0]) if pending else None,
            "overall": overall, "this_run": this_run, "decisions": decisions}


def report(last_n):
    db_path = resolve(config.DB_PATH)
    log_path = resolve(config.LOG_PATH) if config.LOG_PATH else db_path.with_suffix(".online.jsonl")
    now = datetime.now(timezone.utc)
    events, start = tail_events(log_path)
    if start is None:
        print("No run found in the event log yet.")
        return
    started = datetime.fromisoformat(start["timestamp"])
    start_pull = start.get("history_pulls", 0)
    state = database_state(db_path, start_pull)

    # Run status.
    finish = next((e for e in reversed(events) if e.get("event") in ("run_finished", "run_failed")
                   and e.get("run_id") == start.get("run_id")), None)
    last_event = datetime.fromisoformat(events[-1]["timestamp"]) if events else started
    ended = datetime.fromisoformat(finish["timestamp"]) if finish else now
    done = state["pulls"] - start_pull
    elapsed = (ended - started).total_seconds()
    budget = start.get("budget")
    print("=== Run {} | {}".format(start.get("run_id", "?")[:8], "checked " + sgt(now) + " Singapore time"))
    if finish:
        print("Status: FINISHED at {} ({}), stop reason: {}".format(
            sgt(ended), finish["event"], finish.get("stop_reason") or finish.get("error_type")))
    else:
        age = (now - last_event).total_seconds()
        print("Status: RUNNING. Last log event {:.0f} s ago{}".format(
            age, "  <- no activity for over a minute: tuning, retrying, or stopped?" if age > 60 else ""))
    print("Started {} | elapsed {} | method {} {}".format(
        sgt(started), duration(elapsed), start.get("model"), json.dumps(start.get("parameters"))))
    print("Pulls this run: {:,}{} | average {:.2f} pulls/s, pauses included".format(
        done, " of {:,}".format(budget) if isinstance(budget, int) else " (no limit: all remaining)",
        done / elapsed if elapsed > 0 else 0))

    # Per-pull timing from the log tail.
    completed = [e for e in events if e.get("event") == "pull_completed"]
    attempts = {}
    for e in events:
        if e.get("event") == "pull_attempt":
            attempts[(e["request"]["request_id"], e.get("attempt"))] = datetime.fromisoformat(e["timestamp"])
    times = [datetime.fromisoformat(e["timestamp"]) for e in completed]
    cycles = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    responses = []
    for e, t in zip(completed, times):
        sent = attempts.get((e["request"]["request_id"], e.get("attempt")))
        if sent:
            responses.append((t - sent).total_seconds())
    uncertain = sum(e.get("event") == "pull_uncertain" for e in events)
    retried = sum((e.get("attempt") or 1) > 1 for e in completed)
    if cycles:
        recent = times[-min(len(times), 500):]
        recent_speed = (len(recent) - 1) / (recent[-1] - recent[0]).total_seconds() \
            if len(recent) > 1 and recent[-1] > recent[0] else 0
        c, r = spread(cycles), spread(responses) if responses else None
        print("\nTime per pull, over the last {:,} pulls in the log (seconds):".format(c["n"] + 1))
        print("  {:<22} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6} {:>6}".format(
            "", "mean", "sd", "min", "p50", "p90", "p99", "max"))
        for name, s in (("Pull to pull", c), ("Server response", r)):
            if s:
                print("  {:<22} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.3f} {:>6.2f}".format(
                    name, s["mean"], s["sd"], s["min"], s["p50"], s["p90"], s["p99"], s["max"]))
        print("  Slow gaps: {} over 1 s, {} over 5 s. Uncertain responses: {}. Pulls needing a retry: {}.".format(
            sum(x > 1 for x in cycles), sum(x > 5 for x in cycles), uncertain, retried))
        print("  Recent speed (last {} pulls): {:.2f} pulls/s".format(len(recent), recent_speed))
        if recent_speed > 0:
            completion(state, events, start_pull, budget, recent_speed, now, finished=bool(finish))

    # Tuning.
    tuning = [e for e in events if e.get("event", "").startswith("tuning_")]
    if tuning or state["decisions"]:
        print("\nTuning: {} decision(s) saved.".format(len(state["decisions"])))
        for at, payload in state["decisions"][-3:]:
            d = json.loads(payload)
            print("  at pull {:,}: x{:g} ({}), next check at {:,}".format(
                at, d.get("selected_multiplier"), d.get("reason"), d.get("next_at", 0)))
        open_check = tuning and tuning[-1].get("event") == "tuning_started"
        if open_check:
            print("  A tuning check started at {} and is still running (pulls pause meanwhile).".format(
                sgt(datetime.fromisoformat(tuning[-1]["timestamp"]))))

    # Database totals and arms.
    print("\nDatabase: {:,} pulls saved (last index {}), {:,} sign-ups ({:.2%}). Pending request: {}.".format(
        state["pulls"], state["last_pull"], state["signups"],
        state["signups"] / (V * state["pulls"]) if state["pulls"] else 0,
        ("pull {:,} on arm {} in flight (normal while running)" if not finish else
         "pull {:,} on arm {} unresolved; the next online run recovers it first").format(
            state["pending"]["expected_pull"], state["pending"]["arm"]) if state["pending"] else "none"))
    if state["this_run"]:
        print("This run, by arm:")
        for arm, n, s in sorted(state["this_run"], key=lambda row: -row[1]):
            print("  arm {:>2}: {:>7,} pulls ({:5.1%}), {:>9,} sign-ups, {:.2%}".format(
                arm, n, n / done if done else 0, s, s / (V * n)))
    print("All pulls, top 5 arms by rate (95% interval):")
    for arm, n, s in sorted(state["overall"], key=lambda row: -row[2] / row[1])[:5]:
        p = s / (V * n)
        half = 1.96 * math.sqrt(p * (1 - p) / (V * n))
        print("  arm {:>2}: {:>7,} pulls, {:.2%} ({:.2%} to {:.2%})".format(arm, n, p, p - half, p + half))

    # Latest pulls.
    if completed and last_n:
        print("\nLast {} pulls:".format(min(last_n, len(completed))))
        print("  {:>7} {:>4} {:>7} {:>12} {:>9} {:>9}".format("Pull", "Arm", "Reward", "Saved (SGT)", "Gap s", "Server s"))
        for i in range(max(0, len(completed) - last_n), len(completed)):
            e, t = completed[i], times[i]
            gap = (t - times[i - 1]).total_seconds() if i else float("nan")
            sent = attempts.get((e["request"]["request_id"], e.get("attempt")))
            print("  {:>7,} {:>4} {:>7} {:>12} {:>9.3f} {:>9.3f}".format(
                e["result"]["Pull"], e["result"]["Arm"], e["result"]["Reward"], t.astimezone(SGT).strftime("%H:%M:%S"),
                gap, (t - sent).total_seconds() if sent else float("nan")))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--last", type=int, default=10, help="How many recent pulls to list (default 10)")
    parser.add_argument("--watch", type=float, default=0, help="Refresh every this many seconds; Ctrl-C stops")
    args = parser.parse_args()
    try:
        while True:
            report(args.last)
            if args.watch <= 0:
                return 0
            time.sleep(args.watch)
            print("\n" + "-" * 80)
    except KeyboardInterrupt:
        return 0
    except sqlite3.OperationalError as error:
        print("Couldn't read the database just now ({}). Try again in a moment.".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
