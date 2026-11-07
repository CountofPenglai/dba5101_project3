"""Phase 2: simulate 40 combinations on conversion rates drawn from the pilot's Beta posteriors.

Offline only. Reads phase 1's database read-only, makes no pulls, writes CSVs to results/.

    python main.py            Run the 40 combinations, compare them, then validate the leaders
    python main.py check      Check the simulator against hand calculations and program/bandit
    python main.py --reps 20 --total-pulls 50000     Quick trial with smaller settings
"""
import argparse
import csv
import json
import math
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime
from pathlib import Path

import numpy as np

import config
import simulate as sim
from simulate import K, V

HERE = Path(__file__).resolve().parent
NAMES = {'ucb': 'UCB', 'eps': 'e-greedy'}
METHOD_ID = {'ucb': 1, 'eps': 2}
MAIN_STREAM, VALIDATE_STREAM = 1, 2


def label(kind, param, per_arm):
    value = 'x{:g}'.format(param) if kind == 'ucb' else '{:g}'.format(param)
    return '{} {}, {}/arm'.format(NAMES[kind], value, per_arm)


def resolve(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else HERE / path).resolve()


# ------------------------------------------------------------------ inputs
def validate_settings(reps, total_pulls):
    def fail(message):
        raise SystemExit('Settings problem: {} Fix config.py, then run again.'.format(message))

    if not config.UNIFORM_TOTALS or any(type(n) is not int or not 1 <= n <= 10_000
                                        for n in config.UNIFORM_TOTALS):
        fail('UNIFORM_TOTALS must be whole numbers from 1 to 10000.')
    if not config.UCB_MULTIPLIERS or any(not 0 < m <= 100 for m in config.UCB_MULTIPLIERS):
        fail('UCB_MULTIPLIERS must be above 0.')
    if not config.EPSILONS or any(not 0 < e <= 1 for e in config.EPSILONS):
        fail('EPSILONS must be above 0 and at most 1.')
    if config.PRIOR_A <= 0 or config.PRIOR_B <= 0:
        fail('PRIOR_A and PRIOR_B must be above 0.')
    if type(reps) is not int or reps < 2 or type(config.VALIDATE_REPS) is not int or config.VALIDATE_REPS < 2:
        fail('REPS and VALIDATE_REPS must be whole numbers, at least 2.')
    if type(total_pulls) is not int or not 0 < total_pulls <= 1_000_000:
        fail('TOTAL_PULLS must be a whole number up to 1,000,000.')


def load_history(db_path):
    """Pulls and sign-ups per arm from phase 1's database, opened read-only."""
    if not db_path.exists():
        raise SystemExit('No database at {}. Run phase 1 first, or fix DB_PATH.'.format(db_path))
    with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute('SELECT arm, reward FROM results ORDER BY pull').fetchall()
        pending = db.execute('SELECT COUNT(*) FROM pending').fetchone()[0]
    pulls, signups = np.zeros(K, int), np.zeros(K, int)
    for arm, reward in rows:
        pulls[arm] += 1
        signups[arm] += reward
    return pulls, signups, pending


def prob_best(a, b, draws=200_000, seed=0):
    rng = np.random.default_rng(seed)
    wins = np.zeros(K)
    for _ in range(draws // 20_000):
        wins += np.bincount(rng.beta(a, b, size=(20_000, K)).argmax(axis=1), minlength=K)
    return wins / wins.sum()


def print_posterior(pulls, signups, a, b):
    best = prob_best(a, b)
    lo, hi = beta_interval(a, b)
    rows = []
    print('\nStep 2: Beta posterior for each arm, Beta({:g} + sign-ups, {:g} + non-sign-ups)'.format(
        config.PRIOR_A, config.PRIOR_B))
    print('{:>3} {:>5} {:>8} {:>7} {:>16} {:>16} {:>7}'.format(
        'Arm', 'Pulls', 'Sign-ups', 'Rate', 'Beta(a, b)', '95% interval', 'P(best)'))
    for arm in range(K):
        rate = signups[arm] / (V * pulls[arm]) if pulls[arm] else float('nan')
        print('{:>3} {:>5} {:>8} {:>7.2%} {:>16} {:>16} {:>7.1%}'.format(
            arm, pulls[arm], signups[arm], rate, '({:g}, {:g})'.format(a[arm], b[arm]),
            '{:.1%}-{:.1%}'.format(lo[arm], hi[arm]), best[arm]))
        rows.append(dict(arm=arm, pulls=pulls[arm], signups=signups[arm], rate=rate, beta_a=a[arm],
                         beta_b=b[arm], posterior_mean=a[arm] / (a[arm] + b[arm]),
                         ci95_low=lo[arm], ci95_high=hi[arm], prob_best=best[arm]))
    return rows


def beta_interval(a, b, draws=200_000, seed=1):
    sample = np.random.default_rng(seed).beta(a, b, size=(draws, K))
    return np.percentile(sample, 2.5, axis=0), np.percentile(sample, 97.5, axis=0)


# ------------------------------------------------------------- simulation
def make_jobs(combos, worlds, pulls, signups, stream, total_pulls):
    """Group combinations by method and uniform total; each group is one process."""
    groups = {}
    for kind, param, per_arm in combos:
        groups.setdefault((kind, per_arm), []).append(param)
    return [dict(kind=kind, params=params, per_arm=per_arm, worlds=worlds, pulls=pulls,
                 signups=signups, seed=config.SEED, stream=stream, method_id=METHOD_ID[kind],
                 horizon=total_pulls)
            for (kind, per_arm), params in groups.items()]


def run_jobs(jobs, workers):
    rows, started = [], time.time()
    workers = min(len(jobs), workers or max(1, (os.cpu_count() or 2) - 1))
    print('Running {} groups on {} processes.'.format(len(jobs), workers), flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(sim.run_group, job): job for job in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            rows.extend(future.result())
            print('  [{}/{}] {:5.0f}s  {}, {}/arm, {} values'.format(
                done, len(jobs), time.time() - started, NAMES[job['kind']], job['per_arm'],
                len(job['params'])), flush=True)
    return sorted(rows, key=lambda r: (r['kind'], r['per_arm'], r['param']))


def summarize(rows, real_signups):
    """One line per combination, ranked by sign-ups lost against always pulling the true best arm."""
    leader = min(rows, key=lambda r: r['regret'].mean())
    table = []
    for r in rows:
        reps = len(r['regret'])
        diff = r['regret'] - leader['regret']  # Same worlds, so the difference is paired
        table.append(dict(
            combination=label(r['kind'], r['param'], r['per_arm']),
            method=NAMES[r['kind']], param=r['param'], per_arm=r['per_arm'],
            total_signups=real_signups + r['expected_signups'].mean(),
            regret=r['regret'].mean(), regret_se=r['regret'].std(ddof=1) / math.sqrt(reps),
            regret_p95=np.percentile(r['regret'], 95),
            uniform_regret=r['uniform_regret'].mean(),
            vs_leader=diff.mean(), vs_leader_se=diff.std(ddof=1) / math.sqrt(reps),
            picks_best=r['correct'].mean(), best_share=r['best_share'].mean()))
    table.sort(key=lambda row: row['regret'])
    for rank, row in enumerate(table, 1):
        row['rank'] = rank
        row['tied_with_leader'] = rank == 1 or row['vs_leader'] <= 2 * row['vs_leader_se']
    return table


def print_table(table):
    print('{:>4}  {:<24} {:>14} {:>18} {:>20} {:>6} {:>6}'.format(
        'Rank', 'Combination', 'Total sign-ups', 'Lost vs best arm', 'Behind leader', 'Picks', 'Best'))
    print('{:>4}  {:<24} {:>14} {:>18} {:>20} {:>6} {:>6}'.format(
        '', '', '(expected)', '(+/- 2 SE)', '(+/- 2 SE)', 'best', 'share'))
    for row in table:
        behind = '-' if row['rank'] == 1 else '{:,.0f} +/- {:,.0f}{}'.format(
            row['vs_leader'], 2 * row['vs_leader_se'], ' *' if row['tied_with_leader'] else '')
        print('{:>4}  {:<24} {:>14,.0f} {:>18} {:>20} {:>6.0%} {:>6.1%}'.format(
            row['rank'], row['combination'], row['total_signups'],
            '{:,.0f} +/- {:,.0f}'.format(row['regret'], 2 * row['regret_se']), behind,
            row['picks_best'], row['best_share']))
    print('* Within 2 standard errors of the leader: these worlds can\'t separate them.')


def phase3_note(row, pulls):
    print('\nIn phase 3, the leading combination would mean:')
    if row['per_arm'] > pulls.min():
        print('  1. Uniform pulls up to {} per arm: phase 1 with PULLS_PER_ARM = {}.'.format(
            row['per_arm'], row['per_arm']))
    else:
        print('  1. No more uniform pulls: start the method from the pilot data.')
    if row['method'] == 'UCB':
        print('  2. UCB with bonus x{:g}: program/bandit UCBModel(exploration={:g}), '
              'because exploration = 2 x multiplier^2.'.format(row['param'], 2 * row['param'] ** 2))
    else:
        print('  2. e-greedy with e = {:g}: with that chance pull a random arm (any of 24), otherwise the '
              'arm with the highest mean, ties to the lowest arm. program/bandit has no e-greedy model '
              'yet.'.format(row['param']))


# ---------------------------------------------------------------- outputs
def write_csv(path, rows, fields=None):
    with open(path, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fields or list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ('{:.10g}'.format(v) if isinstance(v, (float, np.floating)) else v)
                             for k, v in row.items() if k in writer.fieldnames})


def run_rows(stage, rows):
    out = []
    for r in rows:
        for rep in range(len(r['regret'])):
            out.append(dict(stage=stage, combination=label(r['kind'], r['param'], r['per_arm']),
                            method=NAMES[r['kind']], param=r['param'], per_arm=r['per_arm'], world=rep,
                            expected_signups=r['expected_signups'][rep], regret=r['regret'][rep],
                            uniform_regret=r['uniform_regret'][rep], picks_best=int(r['correct'][rep]),
                            pick_gap=r['pick_gap'][rep], best_share=r['best_share'][rep]))
    return out


def curve_rows(stage, rows):
    return [dict(stage=stage, combination=label(r['kind'], r['param'], r['per_arm']), pull=int(t),
                 mean_regret=value)
            for r in rows for t, value in zip(r['marks'], r['curve'])]


# -------------------------------------------------------------------- run
def run(reps, total_pulls):
    validate_settings(reps, total_pulls)
    db_path, out_dir = resolve(config.DB_PATH), resolve(config.RESULTS_DIR)
    pulls, signups, pending = load_history(db_path)
    used, real_signups = int(pulls.sum()), int(signups.sum())
    print('Phase 2 (offline, no pulls). Database: {}'.format(db_path))
    print('Step 1: {} real pulls, {} sign-ups ({:.2%}).'.format(
        used, real_signups, real_signups / (V * used) if used else 0))
    if pending:
        print('  Note: a request is pending in the database, so phase 1 may still be running.')
    if pulls.min() != pulls.max():
        print('  Warning: arms have {} to {} pulls. The pilot looks unfinished; finish it first '
              'unless that is deliberate.'.format(pulls.min(), pulls.max()))
    if total_pulls <= used + int(np.maximum(0, max(config.UNIFORM_TOTALS) - pulls).sum()):
        raise SystemExit('TOTAL_PULLS leaves no pulls for the methods after the uniform phase.')
    skipped = [n for n in config.UNIFORM_TOTALS if n < pulls.max()]
    if skipped:
        print('  Note: uniform totals {} are below pulls already made; those mean no extra '
              'uniform pulls.'.format(skipped))

    a, b = sim.posterior(pulls, signups, (config.PRIOR_A, config.PRIOR_B))
    posterior_rows = print_posterior(pulls, signups, a, b)

    combos = ([('ucb', m, n) for n in config.UNIFORM_TOTALS for m in config.UCB_MULTIPLIERS]
              + [('eps', e, n) for n in config.UNIFORM_TOTALS for e in config.EPSILONS])
    print('\nStep 3: {} combinations x {} worlds, {:,} pulls each ({:,} real + {:,} simulated).'.format(
        len(combos), reps, total_pulls, used, total_pulls - used))
    worlds = sim.draw_worlds(a, b, reps, config.SEED, MAIN_STREAM)
    oracle = real_signups + V * worlds.max(axis=1).mean() * (total_pulls - used)
    started = time.time()
    rows = run_jobs(make_jobs(combos, worlds, pulls, signups, MAIN_STREAM, total_pulls), config.WORKERS)

    print('\nStep 4a: compare. "Lost vs best arm" counts expected sign-ups lost on the simulated pulls, '
          'compared with\nalways pulling each world\'s true best arm (which would total about {:,.0f} '
          'sign-ups, real pulls included).\n'.format(oracle))
    table = summarize(rows, real_signups)
    print_table(table)

    top = table[:config.VALIDATE_TOP]
    print('\nStep 4b: validate. The top {} rerun on {} fresh worlds, because the best of 40 on the same '
          'worlds\nlooks better than it is.'.format(len(top), config.VALIDATE_REPS))
    fresh = sim.draw_worlds(a, b, config.VALIDATE_REPS, config.SEED, VALIDATE_STREAM)
    kinds = {v: k for k, v in NAMES.items()}
    val_rows = run_jobs(make_jobs([(kinds[r['method']], r['param'], r['per_arm']) for r in top],
                                  fresh, pulls, signups, VALIDATE_STREAM, total_pulls), config.WORKERS)
    validation = summarize(val_rows, real_signups)
    print_table(validation)

    leader = table[0]['combination']
    held = next(r for r in validation if r['combination'] == leader)
    if held['rank'] == 1:
        verdict = 'CONFIRMED: {} leads on fresh worlds too.'.format(leader)
    elif held['tied_with_leader']:
        verdict = ('TIED: {} is within 2 SE of {} on fresh worlds. Either is defensible; the gap is '
                   'too small to measure.'.format(leader, validation[0]['combination']))
    else:
        verdict = ('NOT CONFIRMED: {} falls clearly behind {} on fresh worlds. Increase REPS and '
                   'rerun before choosing.'.format(leader, validation[0]['combination']))
    print('\n' + verdict)
    chosen = table[0]
    grid = config.UCB_MULTIPLIERS if chosen['method'] == 'UCB' else config.EPSILONS
    if chosen['param'] in (min(grid), max(grid)):
        print('Note: {:g} is at the edge of the values tried, so a value beyond it might do even better. '
              'Consider adding one to config.py and rerunning.'.format(chosen['param']))
    phase3_note(validation[0] if held['rank'] != 1 and not held['tied_with_leader'] else table[0], pulls)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / 'posterior.csv', posterior_rows)
    write_csv(out_dir / 'summary.csv', table)
    write_csv(out_dir / 'validation.csv', validation)
    write_csv(out_dir / 'runs.csv', run_rows('compare', rows) + run_rows('validate', val_rows))
    write_csv(out_dir / 'curves.csv', curve_rows('compare', rows) + curve_rows('validate', val_rows))
    with open(out_dir / 'run_info.json', 'w') as handle:
        json.dump(dict(finished=datetime.now().isoformat(timespec='seconds'), database=str(db_path),
                       real_pulls=used, real_signups=real_signups, pending_request=bool(pending),
                       total_pulls=total_pulls, reps=reps, validate_reps=config.VALIDATE_REPS,
                       validate_top=config.VALIDATE_TOP, seed=config.SEED,
                       prior=[config.PRIOR_A, config.PRIOR_B], uniform_totals=config.UNIFORM_TOTALS,
                       ucb_multipliers=config.UCB_MULTIPLIERS, epsilons=config.EPSILONS,
                       oracle_signups=oracle, verdict=verdict, seconds=round(time.time() - started)),
                  handle, indent=2)
    print('\nFinished in {:.0f} minutes. Results: {}'.format((time.time() - started) / 60, out_dir))


# ----------------------------------------------------------------- checks
def check():
    """Compare the simulator with hand calculations and with program/bandit's UCBModel."""
    ok = True

    def report(name, passed, detail):
        nonlocal ok
        ok &= passed
        print('{}  {}: {}'.format('PASS' if passed else 'FAIL', name, detail))

    # 1. UCB chooses exactly what program/bandit's UCBModel would, given the same rewards.
    sys.path.insert(0, str(HERE.parent / 'program'))
    from bandit import UCBModel

    rng = np.random.default_rng(7)
    P = np.array([rng.uniform(.10, .20, K)])
    pulls = np.full(K, 10)
    history, signups, net = [], np.zeros(K, int), 0
    for i in range(10 * K):
        arm = i % K
        reward = int(rng.binomial(V, P[0, arm]))
        net += reward
        signups[arm] += reward
        history.append({'Arm': str(arm), 'Reward': reward, 'NetReward': net, 'Pull': i})
    for multiplier in (0.05, 0.25, 1.0):
        n0, s0 = np.tile(pulls.astype(float), (1, 1)), signups[None, :].astype(float)
        res = sim.run_policy('ucb', [multiplier], P, n0, s0, 10 * K, 10 * K + 3000,
                             np.random.default_rng(8), trace=True)
        model = UCBModel(exploration=2 * multiplier ** 2).fit(history)
        total, mismatches = net, 0
        for step, (arm, reward) in enumerate(zip(res['trace']['arms'], res['trace']['rewards'])):
            mismatches += model.select_arm() != arm
            total += reward
            model.update({'Arm': str(arm), 'Reward': reward, 'NetReward': total, 'Pull': 10 * K + step})
        report('UCB x{:g} matches UCBModel(exploration={:g})'.format(multiplier, 2 * multiplier ** 2),
               mismatches == 0, '{} of 3000 choices differ'.format(mismatches))

    # 2. e = 1 pulls uniformly at random: expected loss = pulls x 100 x mean gap to the best arm.
    lanes, steps = 400, 5000
    P = np.random.default_rng(9).uniform(.10, .20, (lanes, K))
    n0, s0 = np.full((lanes, K), 10.0), np.round(P * V * 10)
    res = sim.run_policy('eps', np.ones(lanes), P, n0, s0, 240, 240 + steps, np.random.default_rng(10))
    simulated = V * (P.max(axis=1) * steps - res['sum_p'])
    formula = V * steps * (P.max(axis=1, keepdims=True) - P).mean(axis=1)
    diff = simulated - formula
    se = diff.std(ddof=1) / math.sqrt(lanes)
    report('e = 1 loss matches the formula', abs(diff.mean()) < 4 * se,
           'simulated {:,.0f}, formula {:,.0f} (SE {:,.0f})'.format(simulated.mean(), formula.mean(), se))

    # 3. e = 0.1 with an obvious leader: loss = pulls x e x 23/24 x 100 x gap.
    P = np.full((lanes, K), .10)
    P[:, 3] = .30
    n0, s0 = np.full((lanes, K), 1000.0), P * V * 1000
    res = sim.run_policy('eps', np.full(lanes, .1), P, n0, s0, 24_000, 24_000 + steps,
                         np.random.default_rng(11))
    simulated = V * (.30 * steps - res['sum_p'])
    expected = steps * .1 * 23 / 24 * V * .20
    se = simulated.std(ddof=1) / math.sqrt(lanes)
    report('e = 0.1 loss matches the formula', abs(simulated.mean() - expected) < 4 * se,
           'simulated {:,.0f}, formula {:,.0f} (SE {:,.0f})'.format(simulated.mean(), expected, se))

    # 4. The uniform phase tops every arm up to exactly the target, and no further.
    P = np.full((3, K), .15)
    start = np.arange(K) * 2  # Some arms start above the target
    n, s, uniform_p, added = sim.top_up(P, start, start * 15, 25, np.random.default_rng(12))
    target = np.maximum(start, 25)
    report('uniform phase tops up to the target', bool((n == target).all()) and added == int((target - start).sum()),
           '{} pulls added, arms now have {} to {} pulls'.format(added, int(n.min()), int(n.max())))

    # 5. The Beta posterior uses sign-ups and non-sign-ups.
    a, b = sim.posterior([10, 10], [150, 0])
    report('Beta posterior', list(a) == [151, 1] and list(b) == [851, 1001],
           'arm with 150/1000 -> Beta(151, 851); arm with 0/1000 -> Beta(1, 1001)')

    print('\nAll checks passed.' if ok else '\nSome checks FAILED. Don\'t trust the simulation until fixed.')
    return 0 if ok else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', nargs='?', default='run', choices=['run', 'check'])
    parser.add_argument('--reps', type=int, default=config.REPS, help='override REPS')
    parser.add_argument('--total-pulls', type=int, default=config.TOTAL_PULLS, help='override TOTAL_PULLS')
    args = parser.parse_args()
    if args.command == 'check':
        sys.exit(check())
    run(args.reps, args.total_pulls)
