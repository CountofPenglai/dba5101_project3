"""Replay and explain every UCB decision since the pilot, from the saved database. No pulls.

    python explain.py

Reads the database read-only (safe while nothing else is writing) and writes:
  results/decisions.csv  one row per pull since the pilot: every number behind UCB's choice
  results/arms.csv       one row per arm: pulls and rates by phase, UCB score now, P(best), forecast
It also prints how long each phase 3 run took, from the event log.

Needs numpy, as phase 2 does.
"""

import csv
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import config
from main import PILOT_PULLS, SINGAPORE, exploration, resolve_path

from bandit import UCBModel  # noqa: E402  (importable once main has loaded phase 1)
from bandit.common import ARMS, DEADLINE, MAX_PULLS, VISITORS_PER_PULL as V  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
LEADER_NOTE = "highest mean rate when the pull was chosen"


def load(db_path):
    with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
        saved = db.execute("SELECT pull, arm, reward, net_reward, model, parameters FROM results ORDER BY pull")
        return [{"Arm": str(arm), "Reward": reward, "NetReward": net, "Pull": pull, "model": model,
                 "parameters": parameters} for pull, arm, reward, net, model, parameters in saved]


def replay(results, e):
    """Refit UCB on the pilot, then step through each later pull and record why it was chosen."""
    model = UCBModel(e).fit(results[:PILOT_PULLS])
    rows = []
    for row in results[PILOT_PULLS:]:
        means = [model.signups[a] / (V * model.counts[a]) for a in range(ARMS)]
        scores = [model._score(a) for a in range(ARMS)]
        arm, choice = int(row["Arm"]), model.select_arm()
        leader = max(range(ARMS), key=lambda a: (means[a], -a))
        runner = max((a for a in range(ARMS) if a != arm), key=lambda a: (scores[a], -a))
        rows.append({
            "pull": row["Pull"], "arm": arm, "replay_matches": arm == choice,
            "mean": means[arm], "bonus": scores[arm] - means[arm], "score": scores[arm],
            "runner_up": runner, "runner_up_score": scores[runner], "margin": scores[arm] - scores[runner],
            "leader": leader, "kind": "exploit" if arm == leader else "explore",
            "mean_gap_to_leader": means[leader] - means[arm], "reward": row["Reward"]})
        model.update(row)
    return model, rows


def p_best(counts, signups, draws=400_000, seed=5101):
    """Share of Beta(1 + sign-ups, 1 + non-sign-ups) draws in which each arm is highest."""
    rng = np.random.default_rng(seed)
    a = 1 + np.asarray(signups, float)
    b = 1 + V * np.asarray(counts, float) - np.asarray(signups, float)
    wins = np.zeros(ARMS)
    for _ in range(draws // 50_000):
        wins += np.bincount(rng.beta(a, b, size=(50_000, ARMS)).argmax(axis=1), minlength=ARMS)
    return wins / wins.sum()


def forecast(model, e):
    """The next pull of each arm if every arm kept its current rate exactly (no luck)."""
    n, s = list(model.counts), [float(x) for x in model.signups]
    rate = [s[a] / (V * n[a]) for a in range(ARMS)]
    t, when = model.total_pulls, {}
    while t < MAX_PULLS and len(when) < ARMS:
        log_t = math.log(t)
        arm = max(range(ARMS), key=lambda a: (s[a] / (V * n[a]) + math.sqrt(e * log_t / n[a]), -a))
        when.setdefault(arm, t)
        n[arm] += 1
        s[arm] += rate[arm] * V
        t += 1
    return when


def same_pulls(results, kind, e, rates, reps=500, seed=5101):
    """Simulate the pulls since the pilot again, from the pilot's data, with each arm's true rate set to `rates`.

    kind 'ucb' is UCBModel(e); kind 'ts' is Thompson Sampling with Beta(1, 1) priors.
    Returns the average new pulls per arm and each repeat's total sign-ups.
    """
    rng = np.random.default_rng([seed, kind == "ts"])
    n0, s0 = np.zeros(ARMS), np.zeros(ARMS)
    for r in results[:PILOT_PULLS]:
        n0[int(r["Arm"])] += 1
        s0[int(r["Arm"])] += r["Reward"]
    n, s = np.tile(n0, (reps, 1)), np.tile(s0, (reps, 1))
    lane, got, rates = np.arange(reps), np.zeros(reps), np.asarray(rates)
    for t in range(PILOT_PULLS, len(results)):
        if kind == "ucb":
            arm = (s / (V * n) + np.sqrt(e * math.log(t) / n)).argmax(axis=1)
        else:
            arm = rng.beta(1 + s, 1 + V * n - s).argmax(axis=1)
        reward = rng.binomial(V, rates[arm])
        n[lane, arm] += 1
        s[lane, arm] += reward
        got += reward
    return (n - n0).mean(axis=0), got


def run_times(log_path):
    """Start, finish and attempts of each UCB run in the event log."""
    runs = {}
    with open(log_path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                event = json.loads(line)
                runs.setdefault(event["run_id"], []).append(event)
    out = []
    for events in runs.values():
        start = next((e for e in events if e["event"] == "run_started"), None)
        finish = next((e for e in events if e["event"] in ("run_finished", "run_failed")), None)
        if start and finish and start["model"] == "ucb":
            began, ended = (datetime.fromisoformat(x["timestamp"]) for x in (start, finish))
            out.append({"start": began, "end": ended, "pulls": finish["completed_pulls"],
                        "attempts": sum(e["event"] == "pull_attempt" for e in events),
                        "seconds": (ended - began).total_seconds(), "parameters": start["parameters"]})
    return out


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "{:.6f}".format(v) if isinstance(v, float) else v for k, v in row.items()})


def main():
    db_path = resolve_path(config.DB_PATH)
    log_path = resolve_path(config.LOG_PATH) if config.LOG_PATH else db_path.with_suffix(".online.jsonl")
    e = exploration()
    results = load(db_path)
    if len(results) <= PILOT_PULLS:
        print("No pulls since the pilot yet.")
        return 0
    model, decisions = replay(results, e)
    after = results[PILOT_PULLS:]
    used = Counter((r["model"], r["parameters"]) for r in after)
    print("Pulls since the pilot: {:,}, saved as {}.".format(
        len(after), ", ".join("{} {} ({:,})".format(m, p, c) for (m, p), c in used.items())))

    # 1. Replay: the same data gives the same choices.
    differ = sum(not d["replay_matches"] for d in decisions)
    print("Replay with UCBModel(exploration={:g}): {} of {:,} pulls differ.".format(e, differ, len(decisions)))

    # 2. Exploit or explore, and what each exploration pull was expected to cost at the time.
    explore = [d for d in decisions if d["kind"] == "explore"]
    print("Exploit pulls (the arm with the {}): {:,}. Explore pulls: {:,} ({:.0%}).".format(
        LEADER_NOTE, len(decisions) - len(explore), len(explore), len(explore) / len(decisions)))
    if explore:
        print("Expected cost of exploring, judged by the means at the time: {:,.0f} sign-ups "
              "(average gap {:.2f} points).".format(sum(d["mean_gap_to_leader"] for d in explore) * V,
                                                    100 * np.mean([d["mean_gap_to_leader"] for d in explore])))
    leaders = Counter(d["leader"] for d in decisions)
    print("Arm with the highest mean, pull by pull: {}.".format(
        ", ".join("arm {} ({:,} pulls)".format(a, c) for a, c in leaders.most_common())))
    print("Median margin of the chosen arm's score over the runner-up: {:.4f}.".format(
        float(np.median([d["margin"] for d in decisions]))))

    # 3. Per arm: pilot, since the pilot, now, P(best) and the forecast.
    pilot, since = Counter(), Counter()
    pilot_s, since_s = Counter(), Counter()
    for r in results[:PILOT_PULLS]:
        pilot[int(r["Arm"])] += 1
        pilot_s[int(r["Arm"])] += r["Reward"]
    for r in after:
        since[int(r["Arm"])] += 1
        since_s[int(r["Arm"])] += r["Reward"]
    first = {}
    for d in decisions:
        first.setdefault(d["arm"], d["pull"])
    pb = p_best(model.counts, model.signups)
    when = forecast(model, e)
    arms = []
    for a in sorted(range(ARMS), key=lambda a: (-model._score(a), a)):
        rate = model.signups[a] / (V * model.counts[a])
        arms.append({
            "arm": a, "pilot_pulls": pilot[a], "pilot_rate": pilot_s[a] / (V * pilot[a]) if pilot[a] else "",
            "pulls_since_pilot": since[a], "rate_since_pilot": since_s[a] / (V * since[a]) if since[a] else "",
            "first_pull_since_pilot": first.get(a, ""), "pulls": model.counts[a], "rate": rate,
            "bonus_now": model._score(a) - rate, "score_now": model._score(a), "p_best": float(pb[a]),
            "next_pull_if_rates_hold": when.get(a, "")})
    print("\n{:>3} {:>12} {:>15} {:>13} {:>8} {:>7} {:>7} {:>13}".format(
        "Arm", "Pilot", "Since pilot", "Now", "Bonus", "Score", "P(best)", "Next pull*"))
    for r in arms:
        print("{:>3} {:>3} {:>8} {:>4} {:>10} {:>4} {:>8} {:>8.4f} {:>7.4f} {:>7} {:>13}".format(
            r["arm"], r["pilot_pulls"], "{:.2%}".format(r["pilot_rate"]), r["pulls_since_pilot"],
            "{:.2%}".format(r["rate_since_pilot"]) if r["pulls_since_pilot"] else "-",
            r["pulls"], "{:.2%}".format(r["rate"]), r["bonus_now"], r["score_now"],
            "{:.1%}".format(r["p_best"]) if r["p_best"] >= 0.001 else "<0.1%",
            "{:,}".format(r["next_pull_if_rates_hold"]) if r["next_pull_if_rates_hold"] != "" else "not by 1M"))
    print("* If every arm kept its current rate exactly. Real pulls add luck, so treat these as a guide.")

    # 4. The same pulls simulated again, with UCB and with Thompson Sampling, from the pilot's data.
    rates = [model.signups[a] / (V * model.counts[a]) for a in range(ARMS)]
    leader = max(range(ARMS), key=lambda a: (rates[a], -a))
    print("\nThe {:,} pulls since the pilot, simulated 500 times from the pilot's data, with each arm's true rate "
          "set to its current estimate:".format(len(after)))
    shown = sorted(range(ARMS), key=lambda a: (-since[a], a))[:3]  # Most pulls in the real run
    print("{:>22} {:>12} {:>16} {:>9} {:>9} {:>9}".format(
        "", "Sign-ups", "Not on arm {}".format(leader), *("Arm {}".format(a) for a in shown)))
    actual = {"arm": [since[a] for a in range(ARMS)], "got": sum(r["Reward"] for r in after)}
    lines = [("Actual run", actual["arm"], [actual["got"]])]
    for kind, name in (("ucb", "UCB x{:g} (simulated)".format(config.UCB_MULTIPLIER)), ("ts", "Thompson (simulated)")):
        pulls, got = same_pulls(results, kind, e, rates)
        lines.append((name, pulls, got))
    for name, pulls, got in lines:
        print("{:>22} {:>12} {:>16.0f} {}".format(
            name, "{:,.0f}".format(np.mean(got)), len(after) - pulls[leader],
            " ".join("{:>9.0f}".format(pulls[a]) for a in shown)))

    # 5. Speed, from the event log.
    print()
    speed = 0
    for run in run_times(log_path):
        speed = run["pulls"] / run["seconds"] if run["seconds"] else 0
        print("UCB run {} to {} Singapore time: {:,} pulls in {:.0f} s ({:.0f} min {:.0f} s), {:.2f} pulls per "
              "second, {:,} attempts.".format(run["start"].astimezone(SINGAPORE).strftime("%d %b %H:%M:%S"),
                                              run["end"].astimezone(SINGAPORE).strftime("%H:%M:%S"), run["pulls"],
                                              run["seconds"], *divmod(run["seconds"], 60), speed, run["attempts"]))
    if speed:  # The latest run's speed
        left = MAX_PULLS - len(results)
        need = timedelta(seconds=left / speed)
        print("At the latest run's speed, the {:,} pulls left take {:.1f} hours. To finish by the deadline, they "
              "must start by {} Singapore time.".format(left, need.total_seconds() / 3600,
                                                        (DEADLINE - need).astimezone(SINGAPORE).strftime("%d %B %H:%M")))
    hours = (DEADLINE - datetime.now(timezone.utc)).total_seconds() / 3600
    print("New pulls close in {:.0f} hours ({} Singapore time).".format(
        hours, DEADLINE.astimezone(SINGAPORE).strftime("%d %B %Y, %H:%M")))

    OUT.mkdir(exist_ok=True)
    write_csv(OUT / "decisions.csv", decisions)
    write_csv(OUT / "arms.csv", arms)
    print("\nWrote {} and {}.".format(OUT / "decisions.csv", OUT / "arms.csv"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
