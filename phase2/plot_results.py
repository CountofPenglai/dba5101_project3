"""Chart of phase 2's findings, from results/runs.csv. Local only: no pulls, no database.

Run from this folder after `python main.py`:
    python plot_results.py
Writes figures/findings.png.

Left: sign-ups lost by every setting when it starts straight from the pilot (10 per arm).
Right: the extra sign-ups lost by adding uniform pulls first, for each method's best setting.
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

HERE = Path(__file__).resolve().parent
RUNS = HERE / "results" / "runs.csv"
OUT_PATH = HERE / "figures" / "findings.png"

# Same palette as phase1/figures/arm_ci.png (validated: categorical slots 1-3).
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
COLOURS = {"UCB": "#2a78d6", "Thompson": "#eb6834", "e-greedy": "#1baf7a"}
NAMES = {"UCB": "UCB", "Thompson": "Thompson Sampling", "e-greedy": "ε-greedy"}


def load(path):
    """Sign-ups lost in each world, per combination, from the comparison stage."""
    worlds = defaultdict(dict)
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            if row["stage"] == "compare":
                key = (row["method"], float(row["param"]), int(row["per_arm"]))
                worlds[key][int(row["world"])] = float(row["regret"])
    return {key: np.array([values[w] for w in sorted(values)]) for key, values in worlds.items()}


def setting_name(method, param):
    if method == "UCB":
        return "UCB ×{:g}{}".format(param, " (standard UCB1)" if param == 1 else "")
    if method == "e-greedy":
        return "ε-greedy ε = {:g}".format(param)
    return "Thompson Sampling"


def compact(value):
    if value >= 1e6:
        return "{:.2g}M".format(value / 1e6)
    if value >= 1e3:
        return "{:,.0f}k".format(value / 1e3) if value >= 1e4 else "{:.1f}k".format(value / 1e3)
    return "{:.0f}".format(value)


def tick(value, _):
    """Clean axis ticks: 100, 1k, 10k, 1M."""
    for size, suffix in ((1e6, "M"), (1e3, "k")):
        if value >= size:
            return "{:g}{}".format(value / size, suffix)
    return "{:g}".format(value)


def interval(values, rng, draws=4000):
    """95% bootstrap interval for the average. Losses are skewed, so +/- 2 SE can go below zero."""
    means = values[rng.integers(0, len(values), (draws, len(values)))].mean(axis=1)
    return np.percentile(means, [2.5, 97.5])


def leaders(data, keys):
    """The best setting, plus any whose paired gap to it is within 2 standard errors."""
    best = min(keys, key=lambda k: data[k].mean())
    tied = []
    for k in keys:
        diff = data[k] - data[best]
        if k == best or diff.mean() <= 2 * diff.std(ddof=1) / math.sqrt(len(diff)):
            tied.append(k)
    return sorted(tied, key=lambda k: data[k].mean())


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.tick_params(which="both", length=0, colors=INK_2)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.set_axisbelow(True)


def main(runs=RUNS, out_path=OUT_PATH):
    data = load(runs)
    base = min(n for _, _, n in data)
    totals = sorted({n for _, _, n in data})
    worlds = len(next(iter(data.values())))

    # Left: every setting that starts straight from the pilot, best at the top.
    rng = np.random.default_rng(0)
    rows = sorted(((data[k].mean(), interval(data[k], rng), k[0], k[1], data[k].max())
                   for k in data if k[2] == base), key=lambda row: -row[0])
    best = {}
    for mean, _, method, param, _ in rows:
        best[method] = param  # Rows run worst to best, so the last one kept is each method's best

    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9})
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 5.6), dpi=200,
                                      gridspec_kw={"width_ratios": [1.35, 1], "wspace": 0.55})
    fig.patch.set_facecolor(SURFACE)

    style(left)
    y = np.arange(len(rows))
    # Axis floor: a decade below the smallest average. Intervals reaching lower run to the edge.
    floor = 10 ** math.floor(math.log10(min(row[0] for row in rows) / 3))
    for yi, (mean, (lo, hi), method, param, worst) in zip(y, rows):
        colour = COLOURS[method]
        left.plot([max(lo, floor), hi], [yi, yi], color=colour, lw=2, solid_capstyle="round", zorder=2)
        left.plot(mean, yi, "o", ms=8, color=colour, mec=SURFACE, mew=2, zorder=3)
        # Two text columns beside the plot: the average, and the single worst world.
        for x, value in ((1.075, mean), (1.24, worst)):
            left.text(x, yi, compact(value), transform=left.get_yaxis_transform(), va="center", ha="right",
                      fontsize=8, color=INK_2)
    for x, header in ((1.075, "Average"), (1.24, "Worst world")):
        left.text(x, len(rows) - 0.35, header, transform=left.get_yaxis_transform(), va="bottom", ha="right",
                  fontsize=8, color=MUTED)
    left.set_yticks(y, [setting_name(m, p) for _, _, m, p, _ in rows], color=INK_2)
    left.set_ylim(-0.7, len(rows) - 0.3)
    left.set_xscale("log")
    left.set_xlim(floor, left.get_xlim()[1])
    left.xaxis.set_major_formatter(FuncFormatter(tick))
    left.grid(axis="x", color=GRID, lw=0.6)
    left.set_xlabel("Expected sign-ups lost vs always pulling the true best arm (log scale)", color=INK_2)
    left.set_title("Every setting, starting straight from the pilot ({} pulls per arm)".format(base),
                   loc="left", fontsize=10, color=INK, pad=10)

    # Right: extra loss from uniform pulls before the method, paired by world.
    style(right)
    ends = []
    for method, param in best.items():
        extra = [data[(method, param, n)] - data[(method, param, base)] for n in totals]
        means = [e.mean() for e in extra]
        right.plot(totals, means, color=COLOURS[method], lw=2, solid_joinstyle="round", zorder=2)
        right.plot(totals, means, "o", ms=8, color=COLOURS[method], mec=SURFACE, mew=2, zorder=3)
        ends.append(means[-1])
    right.set_xticks(totals, [str(n) for n in totals], color=INK_2)
    right.set_xlim(totals[0] - 5, totals[-1] + 5)
    right.set_ylim(bottom=0)
    right.yaxis.set_major_formatter(FuncFormatter(tick))
    right.grid(axis="y", color=GRID, lw=0.6)
    right.set_xlabel("Uniform pulls per arm before the method takes over", color=INK_2)
    right.set_ylabel("Extra sign-ups lost vs starting at {}".format(base), color=INK_2)
    right.set_title("Adding uniform pulls first only costs sign-ups", loc="left", fontsize=10,
                    color=INK, pad=22)
    right.text(0, 1.035, "Each method at its best setting: {}".format(", ".join(
                   setting_name(m, best[m]).replace("ε-greedy ", "").replace("Thompson Sampling", "Thompson")
                   for m in ("Thompson", "UCB", "e-greedy") if m in best)),
               transform=right.transAxes, fontsize=8, color=INK_2, ha="left", va="bottom")
    right.annotate("About {} extra at {} per arm,\nwhichever method follows".format(
                       compact(float(np.mean(ends))), totals[-1]),
                   xy=(totals[-1], float(np.mean(ends))), xytext=(totals[0] + 2, float(np.max(ends)) * 0.82),
                   fontsize=8, color=INK_2, ha="left", va="top",
                   arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8, shrinkA=2, shrinkB=6))

    handles = [Line2D([], [], color=COLOURS[m], marker="o", lw=2, ms=7, mec=SURFACE, mew=1.5, label=NAMES[m])
               for m in ("Thompson", "UCB", "e-greedy") if m in best]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.012, 0.87), ncol=3, frameon=False,
               fontsize=8.5, labelcolor=INK_2, handlelength=1.6, columnspacing=1.8)

    # Headline from the data. Leaders: within 2 paired SE of the best average. Among them, the most
    # reliable is the one whose worst world loses least.
    top = leaders(data, [k for k in data if k[2] == base])
    reliable = min(top, key=lambda k: data[k].max())
    others = [k for k in top if k != reliable]
    name = setting_name(reliable[0], reliable[1])
    if others:
        title = "{} ties for the fewest sign-ups lost, and is the most reliable".format(name)
        risk = "{} tie{} on average but lose{} up to {} in {} worst world, against {} for {}. ".format(
            " and ".join(setting_name(m, p) for m, p, _ in others), "" if len(others) > 1 else "s",
            "" if len(others) > 1 else "s", compact(max(data[k].max() for k in others)),
            "their" if len(others) > 1 else "its", compact(data[reliable].max()), name)
    else:
        title, risk = "{} loses the fewest sign-ups".format(name), ""
    behind = []
    if "e-greedy" in best:
        behind.append("the best ε-greedy setting loses about {}".format(
            compact(data[("e-greedy", best["e-greedy"], base)].mean())))
    if ("UCB", 1.0, base) in data:
        behind.append("standard UCB1 about {}".format(compact(data[("UCB", 1.0, base)].mean())))
    comparison = "; ".join(behind)
    fig.text(0.012, 0.975, title, fontsize=12.5, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.012, 0.935, "{}{}{}.".format(risk, comparison[:1].upper(), comparison[1:]),
             fontsize=9, color=INK_2, ha="left", va="top")
    fig.text(0.012, 0.905, "Simulated, not live: {} possible worlds drawn from the pilot's Beta posteriors, each "
             "played out to 1,000,000 pulls. Lower is better; lines are 95% intervals for the average."
             .format(worlds), fontsize=9, color=INK_2, ha="left", va="top")
    fig.text(0.012, 0.034, "UCB: pull the highest mean + multiplier × √(2 ln t / n). "
             "ε-greedy: pull a random arm with probability ε, else the highest mean. "
             "Thompson: pull the highest draw from each arm's Beta posterior.",
             fontsize=7, color=MUTED, ha="left", va="bottom")
    fig.text(0.012, 0.012, "Every setting runs on the same worlds. Settings named together in the title are "
             "within 2 standard errors of the best, paired by world.",
             fontsize=7, color=MUTED, ha="left", va="bottom")
    fig.subplots_adjust(left=0.165, right=0.975, top=0.76, bottom=0.155)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    print("Saved {}".format(out_path))


if __name__ == "__main__":
    import sys
    main(*sys.argv[1:3])
