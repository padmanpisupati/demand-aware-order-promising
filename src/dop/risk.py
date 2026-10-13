"""Explainable backorder-risk model: logistic regression on a handful of planner-readable features.

Uses scikit-learn when installed; otherwise a pure-Python gradient-descent logistic regression.
"""
from __future__ import annotations
import math, random

FEATURES = ["cover_ratio", "perf_gap", "potential_issue", "deck_risk", "ppap_risk",
            "lead_time_wks", "past_due_flag", "local_bo_flag"]


def featurize(r: dict) -> list[float]:
    cover = (r["national_inv"] + r["in_transit_qty"]) / max(1.0, r["forecast_3_month"])
    return [min(cover, 3.0), 1 - r["perf_6_month_avg"], float(r["potential_issue"] == "Yes"),
            float(r["deck_risk"] == "Yes"), float(r["ppap_risk"] == "Yes"), min(r["lead_time"], 20) / 4,
            float(r["pieces_past_due"] > 0), float(r["local_bo_qty"] > 0)]


class RiskModel:
    def __init__(self):
        self.coef: list[float] = [0.0] * len(FEATURES)
        self.intercept = 0.0
        self.backend = "none"

    def fit(self, rows: list[dict]) -> "RiskModel":
        X = [featurize(r) for r in rows]
        y = [1 if r["went_on_backorder"] == "Yes" else 0 for r in rows]
        try:
            from sklearn.linear_model import LogisticRegression
            m = LogisticRegression(max_iter=1000, class_weight="balanced").fit(X, y)
            self.coef, self.intercept, self.backend = list(m.coef_[0]), float(m.intercept_[0]), "scikit-learn"
        except ImportError:
            self._fit_pure(X, y)
        return self

    def _fit_pure(self, X, y, epochs=300, lr=0.1):
        pos = sum(y) or 1
        w_pos, w_neg = len(y) / (2 * pos), len(y) / (2 * max(1, len(y) - pos))
        for _ in range(epochs):
            g = [0.0] * len(FEATURES); gb = 0.0
            for xi, yi in zip(X, y):
                err = (self._p(xi) - yi) * (w_pos if yi else w_neg)
                gb += err
                for j, v in enumerate(xi):
                    g[j] += err * v
            self.coef = [c - lr * gj / len(X) for c, gj in zip(self.coef, g)]
            self.intercept -= lr * gb / len(X)
        self.backend = "pure-python"

    def _p(self, x):
        z = self.intercept + sum(c * v for c, v in zip(self.coef, x))
        return 1 / (1 + math.exp(-max(-30, min(30, z))))

    def predict(self, r: dict) -> float:
        return self._p(featurize(r))

    def explain(self, r: dict, top: int = 3) -> list[tuple[str, float]]:
        contrib = [(f, c * v) for f, c, v in zip(FEATURES, self.coef, featurize(r))]
        return sorted(contrib, key=lambda t: -abs(t[1]))[:top]


def evaluate(model: RiskModel, rows: list[dict], threshold: float = 0.5) -> dict:
    ps = [model.predict(r) for r in rows]
    ys = [r["went_on_backorder"] == "Yes" for r in rows]
    tp = sum(p >= threshold and y for p, y in zip(ps, ys)); fp = sum(p >= threshold and not y for p, y in zip(ps, ys))
    fn = sum(p < threshold and y for p, y in zip(ps, ys))
    pos = [p for p, y in zip(ps, ys) if y]; neg = [p for p, y in zip(ps, ys) if not y]
    # AUC via rank comparison on a bounded sample (deterministic)
    rng = random.Random(0)
    pairs = [(rng.choice(pos), rng.choice(neg)) for _ in range(20000)] if pos and neg else []
    auc = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a, b in pairs) / max(1, len(pairs))
    return {"n": len(rows), "base_rate": round(sum(ys) / len(ys), 4), "auc": round(auc, 3),
            "precision@0.5": round(tp / max(1, tp + fp), 3), "recall@0.5": round(tp / max(1, tp + fn), 3)}
