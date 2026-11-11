"""Finite-horizon UCB rollout, with independent validation and bounded workers.

Only aggregate statistics enter the worker. NumPy is imported lazily so ordinary
fixed-policy runs remain standard-library-only. See docs/tuning.md for assumptions
and the distinction between empirical safeguards and theoretical guarantees.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .common import ARMS, MAX_PULLS, integer
from .control import StopRequested


@dataclass(frozen=True)
class TuningConfig:
    interval: int = 200_000
    candidates: tuple = (.02, .03, .05, .075, .10)
    train_worlds: int = 96
    validation_worlds: int = 384
    seed: int = 5101
    cvar_level: float = .95
    stage_loss_allowance: float = 0.
    tail_loss_allowance: float = 0.
    min_gain: float = 0.
    min_ess: int = 32
    max_seconds: float = 600.

    def __post_init__(self):
        integer(self.interval, 'tuning interval', minimum=1, maximum=MAX_PULLS)
        for name in ('train_worlds', 'validation_worlds'):
            integer(getattr(self, name), name, minimum=8, maximum=4096)
        integer(self.min_ess, 'min_ess', minimum=2, maximum=4096)
        integer(self.seed, 'seed', maximum=2**32-1)
        if not 1 <= len(self.candidates) <= 12:
            raise ValueError('Use 1 to 12 candidate multipliers')
        for c in self.candidates:
            if isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c) or not 0 < c <= 1:
                raise ValueError('Candidate multipliers must be in (0, 1]')
        for name in ('cvar_level', 'stage_loss_allowance', 'tail_loss_allowance', 'min_gain', 'max_seconds'):
            x = getattr(self, name)
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0:
                raise ValueError('Invalid ' + name)
        if not 0 < self.cvar_level < 1 or self.max_seconds <= 0:
            raise ValueError('Invalid tail level or worker time limit')

    def key(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def draw_worlds(counts, signups, worlds, seed):
    """Defensive importance sampling, q=.5*posterior+.5*challenger mixtures.

    Only a challenger's rate is tilted. Evaluate the complete mixture density,
    not just the sampled component; posterior/q weights are bounded above by 2.
    This samples rare wrong-leader situations without giving them artificial mass.
    """
    import numpy as np
    a, b = 1 + np.asarray(signups), 1 + 100*np.asarray(counts)-np.asarray(signups)
    mean = a / (a+b)
    leader = int(mean.argmax())
    challengers = np.array([i for i in range(ARMS) if i != leader])
    concentration = np.minimum(a+b, 20000.)
    target = np.minimum(.9999, mean[leader] + .5*np.sqrt(mean*(1-mean)/(a+b+1)))
    qa, qb = target*concentration, (1-target)*concentration
    rng = np.random.default_rng(seed)
    p = rng.beta(a, b, size=(worlds, ARMS))
    component = rng.integers(0, len(challengers), size=worlds)
    tilted = rng.random(worlds) < .5
    lanes = np.flatnonzero(tilted)
    chosen = challengers[component[lanes]]
    p[lanes, chosen] = rng.beta(qa[chosen], qb[chosen])
    def lbeta(x, y):
        return np.array([math.lgamma(float(v))+math.lgamma(float(w))-math.lgamma(float(v+w))
                         for v, w in zip(x, y)])
    clipped = np.clip(p[:, challengers], np.finfo(float).tiny, 1-np.finfo(float).eps)
    ratios = ((qa-a)[challengers]*np.log(clipped) +
              (qb-b)[challengers]*np.log1p(-clipped) +
              (lbeta(a, b)-lbeta(qa, qb))[challengers])
    # log-sum-exp including the .5 posterior component prevents overflow.
    log_terms = np.concatenate((np.full((worlds, 1), math.log(.5)),
                                ratios + math.log(.5/len(challengers))), axis=1)
    maximum = log_terms.max(axis=1)
    log_q_over_p = maximum + np.log(np.exp(log_terms-maximum[:, None]).sum(axis=1))
    weights = np.exp(-log_q_over_p)
    return p, weights


def rollout(worlds, counts, signups, candidates, baseline, stage, horizon, seed, trace=False):
    """Exact sequential UCB decisions; O(candidates*worlds*arms) working memory.

    After `stage`, every lane uses baseline as a *learning* continuation policy.
    The policy sees simulated observations, never latent rates. Arrays of full
    response histories are not retained. trace is restricted to a single test lane.
    """
    import numpy as np
    copies, reps = len(candidates), len(worlds)
    p = np.tile(worlds, (copies, 1))
    n = np.tile(np.asarray(counts, dtype=float), (copies*reps, 1))
    s = np.tile(np.asarray(signups, dtype=float), (copies*reps, 1))
    lanes = np.arange(len(p))
    coefficients = np.repeat([round(2*c*c, 12) for c in candidates], reps)[:, None]
    baseline_coefficient = round(2*baseline*baseline, 12)
    mean = np.divide(s, 100*n, out=np.zeros_like(s), where=n > 0)
    inverse = np.divide(1., np.sqrt(n), out=np.full_like(n, np.inf), where=n > 0)
    losses = np.zeros(len(p))
    short = np.zeros(len(p))
    best = p.max(axis=1)
    start = int(sum(counts))
    rng = np.random.default_rng(seed)
    history = [] if trace else None
    if trace and (len(p) != 1 or horizon > 10000):
        raise ValueError('Trace is for small single-lane tests only')
    for step in range(horizon):
        if step == stage:
            coefficients.fill(baseline_coefficient)
        # log(max(t,2)) handles empty histories while unseen arms remain +inf.
        scores = mean + np.sqrt(coefficients * math.log(max(start+step, 2))) * inverse
        arms = scores.argmax(axis=1)
        probabilities = p[lanes, arms]
        reward = rng.binomial(100, probabilities)
        losses += 100*(best-probabilities)
        n[lanes, arms] += 1
        s[lanes, arms] += reward
        mean[lanes, arms] = s[lanes, arms]/(100*n[lanes, arms])
        inverse[lanes, arms] = 1/np.sqrt(n[lanes, arms])
        if step+1 == stage:
            short[:] = losses
        if trace:
            history.append((int(arms[0]), int(reward[0])))
    return {'full': losses.reshape(copies, reps), 'stage': short.reshape(copies, reps),
            'trace': history}


def weighted_cvar(loss, weights, level):
    """Upper-tail empirical CVaR, equivalent to min_eta eta+E[(L-eta)+]/(1-alpha).

    At an atom spanning the quantile, include only the mass needed to complete
    the tail. Averaging all losses >= VaR would be incorrect for discrete data.
    """
    import numpy as np
    loss, weights = np.asarray(loss, dtype=float), np.asarray(weights, dtype=float)
    if (loss.ndim != 1 or weights.shape != loss.shape or not len(loss)
            or not np.isfinite(loss).all() or not np.isfinite(weights).all()
            or (weights < 0).any() or not weights.max() > 0
            or not math.isfinite(level) or not 0 <= level < 1):
        raise ValueError('CVaR requires finite losses, nonnegative mass and 0 <= level < 1')
    weights = weights/weights.max()
    order = np.argsort(-loss)
    w = weights[order]/weights.sum()
    mass = 1-level
    used = np.minimum(w, np.maximum(0., mass-(np.cumsum(w)-w)))
    return float(np.sum(used*loss[order])/mass)


def _mean_error(values, weights):
    import numpy as np
    w = weights/weights.sum()
    mean = float(np.sum(w*values))
    ess = float(1/np.sum(w*w))
    error = float(np.sqrt(np.sum(w*w*(values-mean)**2)*ess/max(ess-1, 1)))
    return mean, error, ess


def _tail_ess(loss, weights, level):
    import numpy as np
    order = np.argsort(-loss)
    mass = weights[order]/weights.sum()
    used = np.minimum(mass, np.maximum(0., 1-level-(np.cumsum(mass)-mass)))
    return float(used.sum()**2/np.sum(used**2))


def validate_switch(candidate, baseline, weights, config):
    """Conservative Monte Carlo screening, NOT a distribution-free guarantee."""
    import numpy as np
    full, full_se, ess = _mean_error(candidate['full']-baseline['full'], weights)
    short, short_se, _ = _mean_error(candidate['stage']-baseline['stage'], weights)
    tail = weighted_cvar(candidate['full'], weights, config.cvar_level) - weighted_cvar(
        baseline['full'], weights, config.cvar_level)
    # Paired bootstrap of proposal draws; retain importance weights in each sample.
    rng = np.random.default_rng(config.seed+12345)
    differences = []
    for _ in range(96):
        ix = rng.integers(0, len(weights), len(weights))
        if weights[ix].sum() <= 0:
            return {'accepted': False, 'reason': 'insufficient_importance_mass'}
        differences.append(weighted_cvar(candidate['full'][ix], weights[ix], config.cvar_level) -
                           weighted_cvar(baseline['full'][ix], weights[ix], config.cvar_level))
    tail_se = float(np.std(differences, ddof=1))
    # At least a few effective tail draws; otherwise never claim tail safety.
    tail_ess = min(_tail_ess(candidate['full'], weights, config.cvar_level),
                   _tail_ess(baseline['full'], weights, config.cvar_level))
    enough = ess >= config.min_ess and tail_ess >= 4
    full_upper, short_upper, tail_upper = full+2.58*full_se, short+2.58*short_se, tail+2.58*tail_se
    accepted = (enough and full_upper < -config.min_gain and
                short_upper <= config.stage_loss_allowance and tail_upper <= config.tail_loss_allowance)
    return {'accepted': bool(accepted), 'ess': ess, 'tail_ess': tail_ess, 'full_regret_difference': full,
            'stage_regret_difference': short, 'cvar_difference': tail,
            'full_difference_upper': full_upper, 'stage_difference_upper': short_upper,
            'cvar_difference_upper': tail_upper, 'reason': 'validated' if accepted else 'safeguard_or_uncertainty'}


def evaluate(stats, remaining, baseline, config):
    import numpy as np
    integer(remaining, 'remaining', maximum=MAX_PULLS)
    from .models import UCBModel
    model = UCBModel(round(2*baseline**2, 12)).fit_aggregates(stats)
    n, s = np.array(model.counts), np.array(model.signups)
    candidates = sorted(set((*config.candidates, baseline)))
    stage = min(config.interval, remaining)
    result = {'selected_multiplier': baseline, 'baseline_multiplier': baseline,
              'horizon': remaining, 'stage_horizon': stage, 'reason': 'baseline_retained',
              'continuation': 'current_multiplier_with_sequential_learning', 'candidates': []}
    if not remaining or not np.all(n > 0):
        result['reason'] = 'no_budget_or_unseen_arms'
        return result
    seed = config.seed + int(n.sum())
    p, w = draw_worlds(n, s, config.train_worlds, seed)
    sample = rollout(p, n, s, candidates, baseline, stage, remaining, seed+1)
    leader = int((s/(100*n)).argmax())
    wrong = p.argmax(axis=1) != leader
    wrong_mass = float(w[wrong].sum()/w.sum())
    for j, c in enumerate(candidates):
        full, error, ess = _mean_error(sample['full'][j], w)
        short = float(np.average(sample['stage'][j], weights=w))
        result['candidates'].append({
            'multiplier': c, 'expected_full_regret': full, 'expected_stage_regret': short,
            'expected_full_signups': float(100*remaining*np.average(p.max(axis=1), weights=w)-full),
            'expected_stage_signups': float(100*stage*np.average(p.max(axis=1), weights=w)-short),
            'full_regret_mc_se': error, 'ess': ess,
            'cvar': weighted_cvar(sample['full'][j], w, config.cvar_level),
            'leader_wrong_probability': wrong_mass,
            'regret_if_leader_wrong': float(np.average(sample['full'][j, wrong], weights=w[wrong]))
                if w[wrong].sum() else None})
    base = next(row for row in result['candidates'] if row['multiplier'] == baseline)
    feasible = [row for row in result['candidates']
                if row['expected_stage_regret'] <= base['expected_stage_regret']+config.stage_loss_allowance
                and row['cvar'] <= base['cvar']+config.tail_loss_allowance]
    chosen = min(feasible, key=lambda row: (row['expected_full_regret'], row['multiplier'] != baseline))
    if chosen['multiplier'] == baseline:
        return result
    # Independent worlds AND independent observation noise, for one preselected challenger.
    vp, vw = draw_worlds(n, s, config.validation_worlds, seed+1000003)
    validation = rollout(vp, n, s, [chosen['multiplier'], baseline], baseline,
                         stage, remaining, seed+1000004)
    gate = validate_switch({k: validation[k][0] for k in ('full', 'stage')},
                           {k: validation[k][1] for k in ('full', 'stage')}, vw, config)
    result['validation'] = gate
    result['proposed_multiplier'] = chosen['multiplier']
    result['reason'] = gate['reason']
    if gate['accepted']:
        result['selected_multiplier'] = chosen['multiplier']
    return result


def evaluate_isolated(stats, remaining, baseline, config, stop=None):
    """Worker has no credentials, network code or history database connection."""
    fallback = {'selected_multiplier': baseline, 'baseline_multiplier': baseline,
                'horizon': remaining, 'stage_horizon': min(config.interval, remaining)}
    if stop:
        stop.check()
    with tempfile.TemporaryDirectory(prefix='gp3-tune-') as folder:
        request, output = Path(folder)/'input.json', Path(folder)/'output.json'
        request.write_text(json.dumps({'stats': stats, 'remaining': remaining,
                                      'baseline': baseline, 'config': asdict(config)}))
        # Allowlist rather than copying authentication/environment from the driver.
        env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'TMPDIR', 'LANG') if key in os.environ}
        env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   PYTHONNOUSERSITE='1')
        proc = subprocess.Popen([sys.executable, '-m', 'bandit.tuning_worker', str(request), str(output)],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        started = time.monotonic()
        try:
            while proc.poll() is None:
                if stop:
                    stop.check()
                if time.monotonic()-started >= config.max_seconds:
                    return {**fallback, 'reason': 'timeout'}
                if stop:
                    stop.wait(.1)
                else:
                    time.sleep(.1)
            if stop:
                stop.check()
            if proc.returncode != 0 or not output.is_file() or output.stat().st_size > 1_000_000:
                return {**fallback, 'reason': 'worker_failed'}
            try:
                result = json.loads(output.read_text())
                if result['selected_multiplier'] not in (*config.candidates, baseline):
                    raise ValueError('Invalid worker selection')
                return result
            except (KeyError, TypeError, ValueError):
                return {**fallback, 'reason': 'invalid_worker_result'}
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            else:
                proc.wait()
