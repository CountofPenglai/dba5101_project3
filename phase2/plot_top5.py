"""Chart: expected and worst-case total sign-ups for phase 2's top 5 options.

Run from this folder after `python main.py`:
    python plot_top5.py
Writes figures/top5_expected_vs_worst.png.

The top 5 are the five combinations that lost the fewest sign-ups in the comparison (Step 4a).
Their figures come from the validation rerun (Step 4b), on 200 fresh worlds the ranking never saw.
  Expected:   the average total sign-ups, the real pilot's sign-ups included.
  Worst case: the always-best-arm total minus the most sign-ups the option lost in any one world.
A world's raw total depends mostly on that world's true rates, the same for every option.
So the worst case holds the world at its average and takes the option's own worst run.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MultipleLocator

HERE = Path(__file__).resolve().parent
RUNS = HERE / "results" / "runs.csv"
INFO = HERE / "results" / "run_info.json"
OUT_PATH = HERE / "figures" / "top5_expected_vs_worst.png"
TOP = 5

# Same palette as figures/findings.png, so each method keeps its colour across the report.
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
COLOURS = {"UCB": "#2a78d6", "Thompson": "#eb6834", "e-greedy": "#1baf7a"}
NAMES = {"UCB": "UCB", "Thompson": "Thompson Sampling", "e-greedy": "ε-greedy"}


def load(path):
    """Per stage and combination: the method, and each world's simulated sign-ups and sign-ups lost."""
    stages = defaultdict(lambda: defaultdict(lambda: {"method": None, "signups": [], "lost": []}))
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            entry = stages[row["stage"]][row["combination"]]
            entry["method"] = row["method"]
            entry["signups"].append(float(row["expected_signups"]))
            entry["lost"].append(float(row["regret"]))
    return stages


def label(combination):
    """'Thompson, 10/arm' -> 'Thompson Sampling, 10/arm'; 'UCB x0.02, 10/arm' -> 'UCB ×0.02, 10/arm'."""
    return combination.replace("Thompson,", "Thompson Sampling,").replace(" x", " ×")


def setting(combination):
    """The method setting without the uniform total: 'UCB ×0.02, 25/arm' -> 'UCB ×0.02'."""
    return label(combination).rsplit(",", 1)[0]


def compact(value):
    return "{:,.0f}k".format(value / 1e3) if value >= 1e4 else "{:.1f}k".format(value / 1e3)


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.tick_params(which="both", length=0, colors=INK_2)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.set_axisbelow(True)


def main(runs=RUNS, info=INFO, out_path=OUT_PATH):
    stages = load(runs)
    real = json.loads(Path(info).read_text())["real_signups"]

    # The top 5 by the comparison, then their figures from the fresh-world validation.
    compare = stages["compare"]
    top = sorted(compare, key=lambda c: np.mean(compare[c]["lost"]))[:TOP]
    options = []
    for combination in top:
        entry = stages["validate"][combination]
        signups, lost = np.array(entry["signups"]), np.array(entry["lost"])
        best_arm = (signups + lost).mean() + real   # Always pulling each world's true best arm
        options.append({"name": combination, "method": entry["method"], "worlds": len(lost),
                        "expected": signups.mean() + real, "worst": best_arm - lost.max(),
                        "worst_lost": lost.max(), "best_arm": best_arm})
    options.sort(key=lambda o: -o["expected"])
    worlds, best_arm = options[0]["worlds"], options[0]["best_arm"]

    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9})
    fig, ax = plt.subplots(figsize=(10, 4.9), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    style(ax)

    y = np.arange(len(options))[::-1]   # Best expected at the top
    for yi, o in zip(y, options):
        colour = COLOURS[o["method"]]
        ax.plot([o["worst"], o["expected"]], [yi, yi], color=AXIS, lw=2, solid_capstyle="round", zorder=1)
        ax.plot(o["worst"], yi, "o", ms=11, mfc=SURFACE, mec=colour, mew=2, zorder=2)
        ax.plot(o["expected"], yi, "o", ms=9, color=colour, mec=SURFACE, mew=2, zorder=3)
        # The two figures as a table beside the plot.
        for x, value in ((1.165, o["expected"]), (1.36, o["worst"])):
            ax.text(x, yi, "{:,.0f}".format(value), transform=ax.get_yaxis_transform(), va="center",
                    ha="right", fontsize=9, color=INK)
    for x, header in ((1.165, "Expected"), (1.36, "Worst case")):
        ax.text(x, len(options) - 0.45, header, transform=ax.get_yaxis_transform(), va="bottom",
                ha="right", fontsize=8.5, color=MUTED)

    ax.set_yticks(y, [label(o["name"]) for o in options], color=INK_2, fontsize=9)
    ax.set_ylim(-0.6, len(options) - 0.4)
    lo = min(o["worst"] for o in options)
    hi = max(o["expected"] for o in options)
    ax.set_xlim(np.floor(lo / 1e5) * 1e5 - 3e4, np.ceil(hi / 1e5) * 1e5 + 1e4)
    ax.xaxis.set_major_locator(MultipleLocator(1e5))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: "{:.1f}M".format(v / 1e6)))
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_xlabel("Total sign-ups over the 1,000,000-pull budget (axis does not start at zero)", color=INK_2)

    handles = [Line2D([], [], ls="none", marker="o", ms=8, color=INK_2, mec=SURFACE, mew=1.5,
                      label="Expected (average)"),
               Line2D([], [], ls="none", marker="o", ms=9, mfc=SURFACE, mec=INK_2, mew=1.8,
                      label="Worst case")]
    handles += [Line2D([], [], ls="none", marker="o", ms=8, color=COLOURS[m], mec=SURFACE, mew=1.5,
                       label=NAMES[m])
                for m in ("Thompson", "UCB", "e-greedy") if any(o["method"] == m for o in options)]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.012, 0.815), ncol=len(handles),
               frameon=False, fontsize=8.5, labelcolor=INK_2, handletextpad=0.4, columnspacing=1.8)

    # Headline from the data: how close the expected totals are, and which settings carry a big downside.
    safest = min(options, key=lambda o: o["worst_lost"])
    riskiest = max(options, key=lambda o: o["worst_lost"])
    risky = sorted({setting(o["name"]) for o in options if o["worst_lost"] > 10 * safest["worst_lost"]})
    spread = hi - min(o["expected"] for o in options)
    if risky:
        title = "The top 5 expect nearly the same sign-ups; {} carr{} the only big downside".format(
            " and ".join(risky), "ies" if len(risky) == 1 else "y")
    else:
        title = "The top 5 expect nearly the same sign-ups, even in the worst case"
    detail = ("Expected totals are within {:,.0f} sign-ups of each other ({:.2%}). One bad world cost {} ({}) "
              "{} sign-ups; {} ({}) never lost more than {}.").format(
        spread, spread / hi, setting(riskiest["name"]), riskiest["name"].rsplit(", ", 1)[1],
        compact(riskiest["worst_lost"]), setting(safest["name"]), safest["name"].rsplit(", ", 1)[1],
        compact(safest["worst_lost"]))
    fig.text(0.012, 0.975, title, fontsize=12.5, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.012, 0.915, detail, fontsize=9, color=INK_2, ha="left", va="top")
    fig.text(0.012, 0.875, "Simulated, not live: Phase 2's validation rerun on {} fresh worlds drawn from the "
             "pilot's Beta posteriors, each played out to 1,000,000 pulls.".format(worlds),
             fontsize=9, color=INK_2, ha="left", va="top")
    fig.text(0.012, 0.045, "Expected: average total sign-ups, the {:,} real pilot sign-ups included. Worst case: "
             "the always-best-arm total ({:,.0f}) minus the most sign-ups the option lost in any one world."
             .format(real, best_arm), fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.text(0.012, 0.015, "10/arm: the method starts straight from the pilot. 25/arm: 15 more uniform pulls "
             "per arm first.", fontsize=7.5, color=MUTED, ha="left", va="bottom")

    fig.subplots_adjust(left=0.2, right=0.735, top=0.71, bottom=0.2)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    print("Saved {}".format(out_path))
    for o in options:
        print("  {:<28} expected {:>12,.0f}   worst case {:>12,.0f}   (worst world lost {:,.0f})".format(
            label(o["name"]), o["expected"], o["worst"], o["worst_lost"]))


if __name__ == "__main__":
    import sys
    main(*sys.argv[1:4])
