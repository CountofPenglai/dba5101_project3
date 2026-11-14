"""Export the final pulls and a summary from the saved database. Read-only; no network.

    python export_results.py

Writes three files to phase3/results/:
  final_pulls.csv.gz     every saved pull: pull, arm, reward, net_reward, model, exploration, saved_at
  tuning_decisions.json  every tuning check, as journaled by the runner
  final_summary.json     totals, integrity checks, stages, arms and leader stability

The SQLite database (over 100 MB) and the JSONL event log (about 1 GB) are too large for GitHub,
so these files are the committed record of the live run.
"""

import gzip
import json
import math
import sqlite3
from pathlib import Path

import numpy as np

import config
import main

OUT = Path(__file__).resolve().parent / "results"
VISITORS = 100
PILOT, CHECKPOINT = 240, 1200


def multiplier(parameters):
    exploration = json.loads(parameters).get("exploration")
    return None if exploration is None else round(math.sqrt(exploration / 2), 6)


def interval(k, m):
    try:
        from scipy.stats import beta
        return [float(beta.ppf(0.025, 1 + k, 1 + m - k)), float(beta.ppf(0.975, 1 + k, 1 + m - k))]
    except ImportError:
        p = (k + 1) / (m + 2)
        h = 1.96 * math.sqrt(p * (1 - p) / (m + 3))
        return [p - h, p + h]


def main_():
    db_path = main.resolve_path(config.DB_PATH)
    db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    rows = db.execute("SELECT pull, arm, reward, net_reward, model, parameters, saved_at "
                      "FROM results ORDER BY pull").fetchall()
    tuning = [json.loads(p) for (p,) in db.execute("SELECT payload FROM tuning_decisions ORDER BY id")]
    pending = db.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
    db.close()

    n = len(rows)
    arm = np.array([r[1] for r in rows], dtype=np.int64)
    reward = np.array([r[2] for r in rows], dtype=np.int64)
    checks = {
        "pulls_saved": n,
        "pull_indices_contiguous": [r[0] for r in rows] == list(range(n)),
        "pending_request": bool(pending),
        "sum_of_rewards": int(reward.sum()),
        "server_net_reward_at_last_pull": rows[-1][3],
        "server_and_database_agree": int(reward.sum()) == rows[-1][3],
    }

    OUT.mkdir(exist_ok=True)
    with gzip.GzipFile(OUT / "final_pulls.csv.gz", "wb", compresslevel=9, mtime=0) as f:
        f.write(b"pull,arm,reward,net_reward,model,exploration,saved_at\n")
        for pull, a, r, net, model, params, saved in rows:
            exploration = json.loads(params).get("exploration", "")
            f.write("{},{},{},{},{},{},{}\n".format(pull, a, r, net, model, exploration, saved).encode())
    (OUT / "tuning_decisions.json").write_text(json.dumps(tuning, indent=1) + "\n", encoding="utf-8")

    pulls = np.bincount(arm, minlength=24)
    signups = np.bincount(arm, weights=reward, minlength=24).astype(np.int64)
    rate = signups / (VISITORS * pulls)
    best = int(rate.argmax())
    loss = (rate[best] - rate[arm]) * VISITORS          # sign-ups lost vs always pulling the leader
    draws = np.random.default_rng(5101).beta(1 + signups, 1 + VISITORS * pulls - signups, size=(200_000, 24))
    p_best = np.bincount(draws.argmax(1), minlength=24) / len(draws)

    bounds = [(0, PILOT, "Pilot", "uniform, 10 pulls per arm"),
              (PILOT, CHECKPOINT, "Stage 1", "UCB x0.05, fixed"),
              (CHECKPOINT, tuning[0]["at_pull"] if tuning else n, "Stage 2", "UCB x0.05, fixed")]
    for i, d in enumerate(tuning):
        end = tuning[i + 1]["at_pull"] if i + 1 < len(tuning) else n
        how = "kept" if d["selected_multiplier"] == d["baseline_multiplier"] else "set"
        bounds.append((d["at_pull"], min(end, n), "Stage 3.{}".format(i + 1),
                       "UCB x{:g}, {} by check {}".format(d["selected_multiplier"], how, i + 1)))
    stages = []
    for lo, hi, name, policy in bounds:
        if hi <= lo:
            continue
        c = np.bincount(arm[lo:hi], minlength=24)
        stages.append({"stage": name, "first_pull": lo, "last_pull": hi - 1, "policy": policy,
                       "multipliers_saved": sorted({multiplier(r[5]) for r in rows[lo:hi]} - {None}),
                       "pulls": hi - lo, "signups": int(reward[lo:hi].sum()),
                       "conversion": round(float(reward[lo:hi].sum() / (VISITORS * (hi - lo))), 6),
                       "share_to_leader": round(float(c[best] / (hi - lo)), 6),
                       "arms_pulled": int(np.count_nonzero(c)),
                       "loss_vs_leader": round(float(loss[lo:hi].sum()), 1)})

    idx = np.nonzero(arm == best)[0]
    blocks = [(int(reward[idx[(idx >= lo) & (idx < lo + 50_000)]].sum()),
               int(VISITORS * ((idx >= lo) & (idx < lo + 50_000)).sum()))
              for lo in range(0, (n // 50_000) * 50_000, 50_000)]
    k, v = np.array([b[0] for b in blocks]), np.array([b[1] for b in blocks])
    pool = k.sum() / v.sum()
    chi2 = float((((k - v * pool) ** 2) / (v * pool * (1 - pool))).sum())
    try:
        from scipy.stats import chi2 as chi2_dist
        chi2_p = float(chi2_dist.sf(chi2, len(k) - 1))
    except ImportError:
        chi2_p = None

    summary = {
        "integrity": checks,
        "totals": {"pulls": n, "visitors": n * VISITORS, "signups": int(reward.sum()),
                   "conversion": round(float(reward.sum() / (VISITORS * n)), 6),
                   "leader": best, "signups_if_always_leader": round(float(rate[best] * VISITORS * n), 1),
                   "loss_vs_leader": round(float(loss.sum()), 1),
                   "loss_vs_leader_pilot": round(float(loss[:PILOT].sum()), 1),
                   "loss_vs_leader_after_pilot": round(float(loss[PILOT:].sum()), 1),
                   "pulls_not_on_leader_after_pilot": int((arm[PILOT:] != best).sum())},
        "stages": stages,
        "arms": [{"arm": int(a), "pulls": int(pulls[a]), "signups": int(signups[a]),
                  "rate": round(float(rate[a]), 6),
                  "interval_95": [round(x, 6) for x in interval(int(signups[a]), int(VISITORS * pulls[a]))],
                  "p_best": float(p_best[a])} for a in np.argsort(-rate)],
        "leader_stability": {"blocks_of_50000_pulls": len(k),
                             "lowest_rate": round(float((k / v).min()), 6),
                             "highest_rate": round(float((k / v).max()), 6),
                             "chi2": round(chi2, 3), "df": len(k) - 1, "p": chi2_p,
                             "variance_ratio_vs_binomial": round(float(
                                 reward[idx].var(ddof=1) / (VISITORS * pool * (1 - pool))), 4)},
        "notes": "Loss vs leader treats each arm's estimated rate as its true rate. "
                 "Intervals are Beta(1 + sign-ups, 1 + non-sign-ups) posteriors.",
    }
    (OUT / "final_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")

    print("Pulls {:,}, sign-ups {:,} ({:.4%}). Integrity: {}".format(
        n, summary["totals"]["signups"], summary["totals"]["conversion"],
        "OK" if checks["pull_indices_contiguous"] and checks["server_and_database_agree"]
        and not checks["pending_request"] else checks))
    for s in stages:
        print("  {:<9} {:>7,} to {:>7,}  {:<26} {:>8,} pulls {:>11,} sign-ups {:.4%}  leader {:.4%}".format(
            s["stage"], s["first_pull"], s["last_pull"], s["policy"], s["pulls"], s["signups"],
            s["conversion"], s["share_to_leader"]))


if __name__ == "__main__":
    main_()
