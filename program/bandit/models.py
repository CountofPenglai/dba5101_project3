"""Incremental bandit policies trained from saved real batch outcomes."""

import math

from .common import ARMS, VISITORS_PER_PULL, normalize_result


class UniformModel:
    """Balance historical pull counts, breaking ties by the lowest arm ID."""

    name = "uniform"

    def __init__(self):
        self.counts = [0] * ARMS
        self.signups = [0] * ARMS
        self.total_pulls = 0

    @property
    def parameters(self):
        return {}

    def fit(self, results):
        self.counts = [0] * ARMS
        self.signups = [0] * ARMS
        self.total_pulls = 0
        for result in results:
            self.update(result)
        return self

    def update(self, result):
        row = normalize_result(result)
        arm = int(row["Arm"])
        self.counts[arm] += 1
        self.signups[arm] += row["Reward"]
        self.total_pulls += 1

    def select_arm(self):
        return min(range(ARMS), key=lambda arm: (self.counts[arm], arm))

    def summary(self):
        return [{"arm": arm, "pulls": self.counts[arm], "signups": self.signups[arm],
                 "conversion_rate": (self.signups[arm] / (VISITORS_PER_PULL * self.counts[arm])
                                     if self.counts[arm] else None)}
                for arm in range(ARMS)]


class UCBModel(UniformModel):
    """Batch-reward UCB; each pull's bounded reward is Reward / 100."""

    name = "ucb"

    def __init__(self, exploration=2.0):
        if (isinstance(exploration, bool) or not isinstance(exploration, (int, float))
                or not math.isfinite(exploration) or exploration <= 0):
            raise ValueError("exploration must be finite and positive")
        super().__init__()
        self.exploration = float(exploration)

    @property
    def parameters(self):
        return {"exploration": self.exploration}

    def _score(self, arm):
        count = self.counts[arm]
        if not count:
            return float("inf")
        mean = self.signups[arm] / (VISITORS_PER_PULL * count)
        return mean + math.sqrt(self.exploration * math.log(self.total_pulls) / count)

    def select_arm(self):
        return max(range(ARMS), key=lambda arm: (self._score(arm), -arm))

    def summary(self):
        rows = super().summary()
        for row in rows:
            row["score"] = self._score(row["arm"]) if row["pulls"] else None
        return rows


def make_model(model):
    if model == "uniform":
        return UniformModel()
    if model == "ucb":
        return UCBModel()
    if isinstance(model, (UniformModel, UCBModel)):
        return model
    raise ValueError("model must be 'uniform', 'ucb', or a model instance")
