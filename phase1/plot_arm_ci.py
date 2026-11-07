"""Ranked 95% interval chart for every arm, from the saved pilot pulls.

Reads the database read-only and makes no server calls. Run from this folder:
    python plot_arm_ci.py
Writes figures/arm_ci.png.
"""
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy import stats

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "../program/data/history.sqlite3"
OUT_PATH = HERE / "figures/arm_ci.png"
VISITORS = 100
CONTENDER_CUTOFF = 0.005  # P(best) at or above this counts as still in contention

# Chart palette (validated: blue/orange pass the CVD and contrast checks)
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
LEADER, CONTENDER, OUT = "#2a78d6", "#eb6834", "#a9a8a2"


def load_rewards(path):
    con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    rows = con.execute("SELECT arm, reward FROM results").fetchall()
    con.close()
    arms = 1 + max(arm for arm, _ in rows)
    signups, pulls = np.zeros(arms), np.zeros(arms)
    for arm, reward in rows:
        signups[arm] += reward
        pulls[arm] += 1
    return signups, pulls * VISITORS


def main():
    signups, visitors = load_rewards(DB_PATH)
    a, b = 1 + signups, 1 + visitors - signups          # Beta posterior, flat prior
    rate = signups / visitors
    lo, hi = stats.beta.ppf(0.025, a, b), stats.beta.ppf(0.975, a, b)
    draws = np.random.default_rng(5101).beta(a, b, size=(400_000, len(a)))
    p_best = np.bincount(draws.argmax(1), minlength=len(a)) / len(draws)

    order = np.argsort(-rate, kind="stable")             # best at the top
    leader = order[0]
    y = np.arange(len(order))[::-1]

    def colour(k):
        if k == leader:
            return LEADER
        return CONTENDER if p_best[k] >= CONTENDER_CUTOFF else OUT

    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9})
    fig, ax = plt.subplots(figsize=(7.2, 7.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ax.axvspan(lo[leader] * 100, hi[leader] * 100, color=LEADER, alpha=0.10, lw=0, zorder=0)
    for yi, k in zip(y, order):
        c = colour(k)
        ax.plot([lo[k] * 100, hi[k] * 100], [yi, yi], color=c, lw=1.8, solid_capstyle="round", zorder=2)
        ax.plot(rate[k] * 100, yi, "o", ms=6.5, color=c, mec=SURFACE, mew=1.5, zorder=3)
        if p_best[k] >= CONTENDER_CUTOFF:
            ax.text(hi[k] * 100 + 0.4, yi, f"P(best) {p_best[k]:.1%}", va="center", ha="left",
                    fontsize=8, color=INK_2)

    ax.set_yticks(y, [f"Arm {k}" for k in order], color=INK_2)
    ax.set_ylim(-0.7, len(order) - 0.3)
    ax.set_xlim(4, 32)
    ax.set_xticks(range(5, 31, 5), [f"{v}%" for v in range(5, 31, 5)], color=INK_2)
    ax.set_xlabel("Sign-up rate (sign-ups per 100 visitors)", color=INK_2)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)

    contenders = [int(k) for k in order[1:] if p_best[k] >= CONTENDER_CUTOFF]
    names = ", ".join(map(str, contenders[:-1])) + f" and {contenders[-1]}"
    fig.text(0.02, 0.975, f"Arm {leader} leads; arms {names} are not yet ruled out",
             fontsize=12, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.02, 0.945, f"Pilot results, {int(visitors[0] // VISITORS)} pulls ({int(visitors[0]):,} visitors) "
             "per arm. Dot = observed rate, line = 95% interval.", fontsize=9, color=INK_2, ha="left", va="top")

    handles = [
        Line2D([], [], color=LEADER, marker="o", lw=1.8, ms=6, mec=SURFACE, label=f"Leader (arm {leader})"),
        Line2D([], [], color=CONTENDER, marker="o", lw=1.8, ms=6, mec=SURFACE,
               label=f"Still in contention (P(best) ≥ {CONTENDER_CUTOFF:.1%})"),
        Line2D([], [], color=OUT, marker="o", lw=1.8, ms=6, mec=SURFACE,
               label=f"Ruled out (P(best) < {CONTENDER_CUTOFF:.1%})"),
        Patch(color=LEADER, alpha=0.10, lw=0, label=f"Arm {leader}'s 95% interval"),
    ]
    legend = ax.legend(handles=handles, loc="lower right", fontsize=8, labelcolor=INK_2,
                       frameon=True, framealpha=1, facecolor=SURFACE, edgecolor="none")
    legend.set_zorder(5)

    fig.text(0.02, 0.012, "95% interval: Beta(1 + sign-ups, 1 + non-sign-ups) posterior. "
             "P(best): share of 400,000 posterior draws in which the arm has the highest rate.",
             fontsize=7, color=MUTED, ha="left", va="bottom")
    fig.subplots_adjust(left=0.11, right=0.97, top=0.91, bottom=0.10)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, facecolor=SURFACE)
    print(f"Saved {OUT_PATH}")


if __name__ == "__main__":
    main()
