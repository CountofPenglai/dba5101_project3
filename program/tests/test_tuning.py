import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


class TuningTests(unittest.TestCase):
    def test_exact_rollout_matches_live_model_and_changes_only_at_boundary(self):
        from bandit.models import UCBModel
        from bandit.tuning import rollout
        n = np.full(24, 10)
        s = np.arange(24) * 5 + 100
        p = np.linspace(.05, .35, 24)[None, :]
        candidate, baseline, horizon, stage = .10, .03, 60, 20
        result = rollout(p, n, s, [candidate], baseline, stage, horizon, seed=13, trace=True)
        model = UCBModel(2 * candidate ** 2).fit_aggregates(
            [{'arm': i, 'pulls': int(n[i]), 'signups': int(s[i])} for i in range(24)])
        total, short = 0., 0.
        for t, (arm, reward) in enumerate(result['trace']):
            if t == stage:
                model.exploration = 2 * baseline ** 2
            self.assertEqual(arm, model.select_arm())
            gap = 100 * (p.max() - p[0, arm])
            total += gap
            if t < stage:
                short += gap
            model.update({'Arm': str(arm), 'Reward': reward,
                          'Pull': 240+t, 'NetReward': sum(model.signups)+reward})
        self.assertAlmostEqual(float(result['full'][0, 0]), total)
        self.assertAlmostEqual(float(result['stage'][0, 0]), short)

    def test_weighted_cvar_accounts_for_partial_boundary_mass(self):
        from bandit.tuning import weighted_cvar
        self.assertAlmostEqual(weighted_cvar(np.array([0., 10., 100.]),
                                            np.array([.8, .19, .01]), .95), 28.)

    def test_cvar_matches_rockafellar_uryasev_formula_with_atoms_and_importance_weights(self):
        from bandit.tuning import weighted_cvar
        rng = np.random.default_rng(9)
        for _ in range(40):
            loss = rng.integers(0, 100, 30).astype(float)
            weights = rng.random(30)**3
            weights[0] = 0
            for level in (0., .5, .95, .999):
                reference = min(eta+np.average(np.maximum(loss-eta, 0), weights=weights)/(1-level)
                                for eta in np.unique(loss))
                actual = weighted_cvar(loss, weights, level)
                self.assertAlmostEqual(actual, reference, places=8)
                self.assertAlmostEqual(weighted_cvar(2*loss+17, 3*weights, level),
                                       2*reference+17, places=8)

    def test_cvar_rejects_invalid_distributions_instead_of_silent_nan(self):
        from bandit.tuning import weighted_cvar
        for loss, weights, level in (([1], [0], .95), ([1], [-1], .95),
                                    ([float('nan')], [1], .95), ([1], [1], 1.),
                                    ([], [], .95), ([1, 2], [1], .95)):
            with self.subTest(loss=loss, weights=weights, level=level), self.assertRaises(ValueError):
                weighted_cvar(np.array(loss), np.array(weights), level)

    def test_worlds_have_full_support_finite_weights_and_reproducible_results(self):
        from bandit.tuning import draw_worlds
        n = np.full(24, 100)
        s = np.full(24, 2000)
        s[21] = 2500
        p, w = draw_worlds(n, s, 2000, 14)
        p2, w2 = draw_worlds(n, s, 2000, 14)
        np.testing.assert_equal(p, p2)
        np.testing.assert_equal(w, w2)
        self.assertTrue(np.isfinite(w).all())
        self.assertTrue((w >= 0).all())
        self.assertAlmostEqual(float(np.average(p[:, 21], weights=w)), 2501/10002, delta=.003)
        self.assertTrue(np.any(p.argmax(axis=1) != 21))

    def test_validation_rejects_short_term_sacrifice_or_tail_regression(self):
        from bandit.tuning import TuningConfig, validate_switch
        weights = np.ones(128)
        base = {'stage': np.full(128, 10.), 'full': np.full(128, 100.)}
        good = {'stage': np.full(128, 9.), 'full': np.full(128, 50.)}
        cfg = TuningConfig()
        self.assertTrue(validate_switch(good, base, weights, cfg)['accepted'])
        bad = {'stage': np.full(128, 11.), 'full': np.full(128, 50.)}
        self.assertFalse(validate_switch(bad, base, weights, cfg)['accepted'])
        bad = {'stage': np.full(128, 9.), 'full': np.r_[np.zeros(120), np.full(8, 200.)]}
        self.assertFalse(validate_switch(bad, base, weights, cfg)['accepted'])

    def test_validation_rejects_tail_supported_by_one_effective_draw(self):
        from bandit.tuning import TuningConfig, validate_switch
        weights = np.r_[np.full(199, .94/199), .06]
        base = {'stage': np.full(200, 10.), 'full': np.r_[np.full(199, 100.), 10000.]}
        candidate = {'stage': np.full(200, 9.), 'full': base['full']-50.}
        result = validate_switch(candidate, base, weights, TuningConfig())
        self.assertFalse(result['accepted'])

    def test_small_evaluation_is_reproducible_and_never_changes_without_validation(self):
        from bandit.tuning import TuningConfig, evaluate
        cfg = TuningConfig(train_worlds=16, validation_worlds=32, interval=12,
                           candidates=(.02, .05), min_ess=4)
        stats = [{'arm': i, 'pulls': 10, 'signups': 100+i*4} for i in range(24)]
        a = evaluate(stats, 30, .05, cfg)
        b = evaluate(stats, 30, .05, cfg)
        self.assertEqual(a, b)
        self.assertEqual(a['horizon'], 30)
        self.assertEqual(a['stage_horizon'], 12)
        if a['selected_multiplier'] != .05:
            self.assertTrue(a['validation']['accepted'])

    def test_worker_timeout_and_stop_terminate_and_reap(self):
        from bandit.tuning import TuningConfig, evaluate_isolated
        from bandit.control import StopController, StopRequested
        class Process:
            returncode = None
            killed = False
            waited = False
            def poll(self): return None
            def terminate(self): self.killed = True
            def wait(self, timeout=None): self.waited = True; return 0
            def kill(self): self.killed = True
        proc = Process()
        cfg = TuningConfig(max_seconds=.001)
        with patch('bandit.tuning.subprocess.Popen', return_value=proc):
            result = evaluate_isolated([], 10, .05, cfg)
        self.assertEqual(result['reason'], 'timeout')
        self.assertTrue(proc.killed and proc.waited)
        event = threading.Event(); event.set()
        with self.assertRaises(StopRequested):
            evaluate_isolated([], 10, .05, cfg, StopController(event))


if __name__ == '__main__':
    unittest.main()
