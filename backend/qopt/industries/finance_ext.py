"""Finance: multi-bit investment allocation, fraud-detection feature selection, transaction scheduling."""
from __future__ import annotations

from typing import List, Optional

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..core.expr import Expr, quicksum
from ..core.model import Model, _binary_expansion_weights
from .base import IndustryProblem


# ----------------------------------------------------------------------------- investment allocation
class AllocationInput(BaseModel):
    assets: List[str] = Field(min_length=2, max_length=8)
    expected_returns: List[float]
    covariance: List[List[float]]
    total_units: int = Field(ge=1, le=31, description="capital split into this many equal units")
    max_units: Optional[List[int]] = Field(default=None, description="per-asset cap in units (default: total_units)")
    risk_aversion: float = Field(default=1.0, ge=0)
    unit_label: str = "unit of capital"

    @model_validator(mode="after")
    def _check(self):
        n = len(self.assets)
        if len(self.expected_returns) != n:
            raise ValueError("one expected return per asset")
        C = np.asarray(self.covariance, float)
        if C.shape != (n, n) or not np.allclose(C, C.T, atol=1e-9):
            raise ValueError("covariance must be a symmetric n×n matrix")
        if np.linalg.eigvalsh(C).min() < -1e-8:
            raise ValueError("covariance must be positive semidefinite")
        if self.max_units is not None:
            if len(self.max_units) != n or any(not 0 <= m <= self.total_units for m in self.max_units):
                raise ValueError("max_units: one value per asset in [0, total_units]")
            if sum(self.max_units) < self.total_units:
                raise ValueError("max_units cannot add up to total_units — infeasible")
        return self

    def caps(self) -> List[int]:
        return self.max_units or [self.total_units] * len(self.assets)


class InvestmentAllocation(IndustryProblem):
    key = "finance.investment_allocation"
    industry = "finance"
    title = "Investment allocation with discrete weights"
    description = ("Split a budget into integer units across assets (multi-bit encoding per asset), maximising "
                   "expected return minus a mean–variance risk penalty, investing exactly the whole budget.")
    formulation = ("w_i = Σ_k c_k b_ik  (bounded binary expansion, w_i ∈ {0..m_i}),  f_i = w_i / U\n"
                   "min  q Σ_ij σ_ij f_i f_j − Σ_i μ_i f_i\n"
                   "s.t. Σ_i w_i = U")
    limitations = ("Weight resolution is 1/U. Qubits grow as Σ_i ⌈log2(m_i+1)⌉; returns and covariances are "
                   "inputs you must estimate (no market data is fetched).")
    Input = AllocationInput

    def _bits(self, d: AllocationInput):
        return [_binary_expansion_weights(m) for m in d.caps()]

    def build_model(self, d: AllocationInput) -> Model:
        m = Model("investment_allocation")
        U = d.total_units
        W: List[Expr] = []
        for i, ws in enumerate(self._bits(d)):
            W.append(quicksum(c * m.binary(f"w_{i}_{k}") for k, c in enumerate(ws)))
        f = [w / U for w in W]
        n = len(f)
        risk = quicksum(d.covariance[i][j] * (f[i] * f[j]) for i in range(n) for j in range(n))
        m.minimize(d.risk_aversion * risk - quicksum(d.expected_returns[i] * f[i] for i in range(n)))
        m.add_constraint(quicksum(W) == U, "invest_all")
        return m

    def interpret(self, d: AllocationInput, a):
        units = [int(sum(c * a[f"w_{i}_{k}"] for k, c in enumerate(ws))) for i, ws in enumerate(self._bits(d))]
        w = np.array(units) / d.total_units
        C = np.asarray(d.covariance)
        return {"units": dict(zip(d.assets, units)), "weights": {s: round(float(x), 4) for s, x in zip(d.assets, w)},
                "unit": d.unit_label, "expected_return": float(np.dot(d.expected_returns, w)),
                "portfolio_variance": float(w @ C @ w), "budget_ok": sum(units) == d.total_units,
                "caps_ok": all(u <= c for u, c in zip(units, d.caps()))}

    def example(self):
        return {"assets": ["EQUITY", "BONDS", "GOLD"], "expected_returns": [0.10, 0.05, 0.07],
                "covariance": [[0.040, 0.002, 0.001], [0.002, 0.010, 0.0005], [0.001, 0.0005, 0.020]],
                "total_units": 6, "risk_aversion": 2.0, "unit_label": "₹1 lakh (sample data)"}


# ----------------------------------------------------------------------------- fraud feature selection
class FeatureSelectionInput(BaseModel):
    feature_names: List[str] = Field(min_length=2, max_length=20)
    samples: List[List[float]] = Field(min_length=4, max_length=5000, description="rows of feature values")
    labels: List[int] = Field(description="1 = fraud, 0 = legitimate, one per row")
    num_features: int = Field(ge=1)
    redundancy_weight: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _check(self):
        n = len(self.feature_names)
        if any(len(r) != n for r in self.samples):
            raise ValueError("every sample row needs one value per feature")
        if len(self.labels) != len(self.samples) or set(self.labels) - {0, 1}:
            raise ValueError("labels must be 0/1, one per sample")
        if len(set(self.labels)) < 2:
            raise ValueError("labels must contain both fraud (1) and legitimate (0) examples")
        if self.num_features > n:
            raise ValueError("num_features exceeds the number of features")
        if not np.all(np.isfinite(np.asarray(self.samples, float))):
            raise ValueError("samples must be finite numbers")
        return self


def feature_statistics(d: FeatureSelectionInput):
    """|Pearson r| of each feature with the label (relevance) and between features (redundancy).
    Zero-variance features get r = 0 and are reported."""
    X = np.asarray(d.samples, float)
    y = np.asarray(d.labels, float)
    Z = np.column_stack([X, y])
    sd = Z.std(axis=0)
    const = [d.feature_names[i] for i in range(X.shape[1]) if sd[i] == 0]
    Zc = (Z - Z.mean(axis=0)) / np.where(sd == 0, 1.0, sd)
    R = np.abs(Zc.T @ Zc / len(Z))
    R[sd == 0, :] = 0.0
    R[:, sd == 0] = 0.0
    n = X.shape[1]
    return R[:n, n], R[:n, :n], const


class FraudFeatureSelection(IndustryProblem):
    key = "finance.fraud_feature_selection"
    industry = "finance"
    title = "Fraud-detection feature selection"
    description = ("Choose K transaction features for a fraud model that are most correlated with the fraud label "
                   "and least redundant with each other (QUBO feature selection, computed from your labelled data).")
    formulation = ("r_i = |corr(feature_i, fraud)|,  ρ_ij = |corr(feature_i, feature_j)|\n"
                   "min  −Σ_i r_i x_i + α Σ_{i<j} ρ_ij x_i x_j\n"
                   "s.t. Σ_i x_i = K")
    limitations = ("Uses linear (Pearson) association only; it ranks features, it does not train or evaluate a fraud "
                   "classifier. Validate the selected set with your own model and hold-out data.")
    Input = FeatureSelectionInput

    def build_model(self, d: FeatureSelectionInput) -> Model:
        rel, red, const = feature_statistics(d)
        m = Model("fraud_feature_selection")
        xs = m.binaries([f"f_{i}" for i in range(len(d.feature_names))])
        n = len(xs)
        m.minimize(-quicksum(float(rel[i]) * xs[i] for i in range(n))
                   + d.redundancy_weight * quicksum(float(red[i, j]) * xs[i] * xs[j]
                                                    for i in range(n) for j in range(i + 1, n)))
        m.add_constraint(quicksum(xs) == d.num_features, "select_k")
        m.metadata["zero_variance_features"] = const
        return m

    def interpret(self, d: FeatureSelectionInput, a):
        rel, red, const = feature_statistics(d)
        sel = [i for i in range(len(d.feature_names)) if a[f"f_{i}"]]
        pairs = [(i, j) for k, i in enumerate(sel) for j in sel[k + 1:]]
        return {"selected_features": [d.feature_names[i] for i in sel],
                "relevance": {d.feature_names[i]: round(float(rel[i]), 4) for i in sel},
                "mean_pairwise_redundancy": float(np.mean([red[i, j] for i, j in pairs])) if pairs else 0.0,
                "zero_variance_features": const, "count_ok": len(sel) == d.num_features}

    def example(self):
        rng = np.random.default_rng(42)
        n = 60
        y = (rng.random(n) < 0.3).astype(int)
        amount = y * 1.5 + rng.normal(0, 0.6, n)
        rows = np.column_stack([
            amount,                                   # amount z-score (strong)
            amount + rng.normal(0, 0.1, n),           # near-duplicate of amount
            y * 0.9 + rng.normal(0, 0.8, n),          # velocity (moderate)
            y * 0.6 + rng.normal(0, 0.9, n),          # merchant risk (weak)
            rng.normal(0, 1, n),                      # device age (noise)
            rng.integers(0, 24, n).astype(float),     # hour of day (noise)
            y * 1.0 + rng.normal(0, 0.7, n),          # geo mismatch (moderate, independent)
            rng.normal(0, 1, n)])                     # pure noise
        return {"feature_names": ["amount_zscore", "amount_zscore_dup", "velocity_1h", "merchant_risk",
                                  "device_age", "hour_of_day", "geo_mismatch", "noise"],
                "samples": np.round(rows, 3).tolist(), "labels": y.tolist(), "num_features": 3,
                "redundancy_weight": 1.0}


# ----------------------------------------------------------------------------- transaction scheduling
class TxInput(BaseModel):
    transactions: List[str] = Field(min_length=1, max_length=10)
    amounts: List[int] = Field(description="integer amount units per transaction")
    windows: List[str] = Field(min_length=1, max_length=5, description="settlement windows")
    cost: List[List[float]] = Field(description="transaction×window cost (fees + delay penalty)")
    window_capacity: List[int] = Field(description="liquidity per window in amount units")
    allowed_windows: Optional[List[List[int]]] = Field(default=None, description="per transaction (deadlines)")

    @model_validator(mode="after")
    def _check(self):
        T, W = len(self.transactions), len(self.windows)
        if len(self.amounts) != T or any(a <= 0 for a in self.amounts):
            raise ValueError("one positive amount per transaction")
        if len(self.cost) != T or any(len(r) != W for r in self.cost):
            raise ValueError("cost must be transactions×windows")
        if len(self.window_capacity) != W or any(c < 0 for c in self.window_capacity):
            raise ValueError("one non-negative capacity per window")
        if self.allowed_windows is not None:
            if len(self.allowed_windows) != T:
                raise ValueError("allowed_windows: one list per transaction")
            for t, aw in enumerate(self.allowed_windows):
                if not aw or any(not 0 <= w < W for w in aw) or len(set(aw)) != len(aw):
                    raise ValueError(f"transaction {self.transactions[t]}: invalid allowed windows")
        if sum(self.amounts) > sum(self.window_capacity):
            raise ValueError("total amount exceeds total window liquidity — infeasible")
        return self

    def allowed(self, t: int) -> List[int]:
        return sorted(self.allowed_windows[t]) if self.allowed_windows else list(range(len(self.windows)))


class TransactionScheduling(IndustryProblem):
    key = "finance.transaction_scheduling"
    industry = "finance"
    title = "Transaction settlement scheduling"
    description = "Assign each transaction to a settlement window before its deadline, within per-window liquidity."
    formulation = ("min  Σ_tw c_tw x_tw\n"
                   "s.t. Σ_w x_tw = 1           ∀ transactions (allowed windows only)\n"
                   "     Σ_t a_t x_tw ≤ L_w     ∀ windows (slack-encoded)")
    Input = TxInput

    def build_model(self, d: TxInput) -> Model:
        m = Model("transaction_scheduling")
        X = {(t, w): m.binary(f"s_{t}_{w}") for t in range(len(d.transactions)) for w in d.allowed(t)}
        m.minimize(quicksum(d.cost[t][w] * x for (t, w), x in X.items()))
        for t in range(len(d.transactions)):
            names = [f"s_{t}_{w}" for w in d.allowed(t)]
            m.add_one_hot(names, f"settle_{t}")
        for w in range(len(d.windows)):
            terms = [(d.amounts[t], X[(t, w)]) for t in range(len(d.transactions)) if (t, w) in X]
            if sum(a for a, _ in terms) > d.window_capacity[w]:
                m.add_constraint(quicksum(a * x for a, x in terms) <= d.window_capacity[w], f"liquidity_{w}")
        return m

    def interpret(self, d: TxInput, a):
        plan = {w: [] for w in d.windows}
        cost, count = 0.0, {}
        for t in range(len(d.transactions)):
            for w in d.allowed(t):
                if a.get(f"s_{t}_{w}"):
                    plan[d.windows[w]].append(d.transactions[t])
                    cost += d.cost[t][w]
                    count[t] = count.get(t, 0) + 1
        load = {d.windows[w]: sum(d.amounts[d.transactions.index(x)] for x in plan[d.windows[w]])
                for w in range(len(d.windows))}
        return {"schedule": plan, "window_load": load, "total_cost": cost,
                "liquidity_ok": all(load[d.windows[w]] <= d.window_capacity[w] for w in range(len(d.windows))),
                "each_settled_once_ok": all(count.get(t) == 1 for t in range(len(d.transactions)))}

    def example(self):
        return {"transactions": ["TX-101", "TX-102", "TX-103", "TX-104"], "amounts": [5, 3, 4, 2],
                "windows": ["09:00", "12:00", "16:00"],
                "cost": [[1, 2, 4], [2, 1, 3], [1, 3, 5], [3, 2, 1]],
                "window_capacity": [8, 7, 6], "allowed_windows": [[0, 1, 2], [0, 1, 2], [0, 1], [0, 1, 2]]}
