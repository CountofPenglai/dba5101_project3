"""Phase 2 simulation engine. Local only: no network requests, no database access.

A "world" is one plausible set of 24 true conversion rates, drawn from each arm's
Beta posterior. Every combination is run on the same worlds, so they are compared
fairly (paired). Pulls are simulated one at a time, exactly as the live driver
would make them; numpy runs many worlds side by side.
"""
import math

import numpy as np

K = 24     # Arms
V = 100    # Visitors per pull
CHUNK = 4096


def posterior(pulls, signups, prior=(1.0, 1.0)):
    """Beta(prior_a + sign-ups, prior_b + non-sign-ups) for each arm."""
    pulls = np.asarray(pulls, float)
    signups = np.asarray(signups, float)
    return prior[0] + signups, prior[1] + V * pulls - signups


def draw_worlds(a, b, reps, seed, stream):
    """reps x K true rates. Each stream is an independent set of worlds."""
    return np.random.default_rng([seed, stream]).beta(a, b, size=(reps, K))


def top_up(P, pulls, signups, per_arm, rng):
    """Uniform pulls until every arm has `per_arm` pulls.

    Returns pulls (reps x K), sign-ups (reps x K), the expected sign-ups those
    uniform pulls earned per world, and how many pulls were added. Pull order
    within the uniform phase doesn't affect anything later, so each arm's extra
    sign-ups are drawn in one go.
    """
    extra = np.maximum(0, per_arm - np.asarray(pulls, int))
    n = np.broadcast_to(np.asarray(pulls, float) + extra, P.shape).copy()
    s = np.asarray(signups, float) + rng.binomial(V * extra, P)
    return n, s, (P * extra).sum(axis=1), int(extra.sum())


def checkpoints(start, horizon, count=40):
    if horizon <= start:
        return np.array([], int)
    return np.unique(np.geomspace(start + 1, horizon, count).astype(int))


def run_policy(kind, param, P, n, s, start, horizon, rng, trace=False, prior=(1.0, 1.0)):
    """Simulate pulls start..horizon-1 one at a time. Lane i uses param[i].

    kind 'ucb': pull argmax of mean + param * sqrt(2 ln t / n), with t the pulls
                made so far. This is program/bandit's UCBModel with
                exploration = 2 * param**2. Ties go to the lowest arm.
    kind 'eps': with probability param, pull a uniformly random arm (any of the
                24); otherwise pull the arm with the highest mean.
    kind 'ts':  Thompson Sampling. Draw one rate from every arm's
                Beta(prior_a + sign-ups, prior_b + non-sign-ups) and pull the
                highest draw. param is ignored.
    """
    lanes = len(P)
    n, s = n.astype(float), s.astype(float)
    mu = s / (V * n)
    nf, sf, mf, Pf = n.reshape(-1), s.reshape(-1), mu.reshape(-1), P.reshape(-1)
    base = np.arange(lanes) * K
    param = np.asarray(param, float)
    if kind == 'ucb':
        isq = 1 / np.sqrt(n)
        qf = isq.reshape(-1)
        coef = (param * math.sqrt(2))[:, None]
    elif kind == 'ts':
        beta_a, beta_b = prior[0] + s, prior[1] + V * n - s
        af, bf = beta_a.reshape(-1), beta_b.reshape(-1)
    elif kind != 'eps':
        raise ValueError(kind)

    best = P.max(axis=1)
    sum_p = np.zeros(lanes)
    marks = checkpoints(start, horizon)
    curve = np.zeros((len(marks), lanes))
    mark = 0
    log = {'arms': [], 'rewards': []} if trace else None

    t = start
    while t < horizon:
        steps = min(CHUNK, horizon - t)
        if kind == 'eps':
            explore = rng.random((steps, lanes)) < param
            random_arm = rng.integers(0, K, (steps, lanes))
        for i in range(steps):
            if kind == 'ucb':
                arms = (mu + coef * math.sqrt(math.log(t)) * isq).argmax(axis=1)
            elif kind == 'ts':
                arms = rng.beta(beta_a, beta_b).argmax(axis=1)
            else:
                arms = np.where(explore[i], random_arm[i], mu.argmax(axis=1))
            flat = base + arms
            p = Pf[flat]
            sum_p += p
            reward = rng.binomial(V, p)
            pulls = nf[flat] + 1
            nf[flat] = pulls
            total = sf[flat] + reward
            sf[flat] = total
            mf[flat] = total / (V * pulls)
            if kind == 'ucb':
                qf[flat] = 1 / np.sqrt(pulls)
            elif kind == 'ts':
                af[flat] = prior[0] + total
                bf[flat] = prior[1] + V * pulls - total
            if trace:
                log['arms'].append(int(arms[0]))
                log['rewards'].append(int(reward[0]))
            t += 1
            if mark < len(marks) and t == marks[mark]:
                curve[mark] = V * (best * (t - start) - sum_p)
                mark += 1

    lane = np.arange(lanes)
    pick = mu.argmax(axis=1)
    true_best = P.argmax(axis=1)
    out = dict(
        sum_p=sum_p,
        pick=pick,
        correct=pick == true_best,
        pick_gap=V * (best - P[lane, pick]),
        best_share=n[lane, true_best] / n.sum(axis=1),
        marks=marks,
        curve=curve,
    )
    if trace:
        out['trace'] = log
    return out


def run_group(job):
    """One method and one uniform total, with every parameter value as its own lanes.

    Process-pool entry point. All parameter values share the same worlds and the
    same uniform-phase data, so differences between them come from the method.
    """
    P, pulls, signups = job['worlds'], job['pulls'], job['signups']
    reps, params = len(P), list(job['params'])
    seed, stream, per_arm = job['seed'], job['stream'], job['per_arm']

    # Same seed for UCB and e-greedy, so both see the same uniform-phase data.
    n, s, uniform_p, added = top_up(P, pulls, signups, per_arm,
                                    np.random.default_rng([seed, stream, 1, per_arm]))
    start = int(np.sum(pulls)) + added
    horizon = max(start, job['horizon'])
    rng = np.random.default_rng([seed, stream, 2, job['method_id'], per_arm])
    tile = len(params)
    res = run_policy(job['kind'], np.repeat(params, reps), np.tile(P, (tile, 1)),
                     np.tile(n, (tile, 1)), np.tile(s, (tile, 1)), start, horizon, rng,
                     prior=job.get('prior', (1.0, 1.0)))

    best = P.max(axis=1)
    uniform_regret = V * (best * added - uniform_p)
    simulated = horizon - int(np.sum(pulls))
    rows = []
    for j, value in enumerate(params):
        lanes = slice(j * reps, (j + 1) * reps)
        sum_p = uniform_p + res['sum_p'][lanes]
        rows.append(dict(
            kind=job['kind'], param=value, per_arm=per_arm,
            uniform_pulls=added, method_pulls=horizon - start,
            expected_signups=V * sum_p,
            regret=V * (best * simulated - sum_p),
            uniform_regret=uniform_regret,
            correct=res['correct'][lanes],
            pick_gap=res['pick_gap'][lanes],
            best_share=res['best_share'][lanes],
            marks=res['marks'],
            curve=res['curve'][:, lanes].mean(axis=1) + uniform_regret.mean(),
        ))
    return rows
