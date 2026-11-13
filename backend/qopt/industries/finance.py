from __future__ import annotations

from typing import List, Optional

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


class PortfolioInput(BaseModel):
    assets: List[str] = Field(min_length=2, max_length=60)
    expected_returns: List[float] = Field(description="expected return per asset over the horizon (fraction)")
    covariance: List[List[float]] = Field(description="return covariance matrix (PSD)")
    costs: List[int] = Field(description="cost of one position per asset, in integer budget units")
    budget: int = Field(gt=0, description="maximum total cost in the same integer units")
    risk_aversion: float = Field(default=0.5, ge=0)
    num_assets: Optional[int] = Field(default=None, ge=1, description="optional exact number of assets to hold")
    budget_unit: str = "unit"

    @model_validator(mode="after")
    def _check(self):
        n = len(self.assets)
        if len(self.expected_returns) != n or len(self.costs) != n:
            raise ValueError("expected_returns and costs must have one entry per asset")
        C = np.asarray(self.covariance, float)
        if C.shape != (n, n):
            raise ValueError("covariance must be n×n")
        if not np.allclose(C, C.T, atol=1e-9):
            raise ValueError("covariance must be symmetric")
        if np.linalg.eigvalsh(C).min() < -1e-8:
            raise ValueError("covariance must be positive semidefinite")
        if any(c < 0 for c in self.costs):
            raise ValueError("costs must be non-negative")
        if self.num_assets is not None and self.num_assets > n:
            raise ValueError("num_assets exceeds number of assets")
        return self


class PortfolioSelection(IndustryProblem):
    key = "finance.portfolio"
    industry = "finance"
    title = "Risk-aware portfolio asset selection"
    description = ("Select a subset of assets maximising expected return minus a risk penalty, subject to a "
                   "budget and optionally an exact cardinality (Markowitz mean–variance, binary holdings).")
    formulation = ("min  q·Σ_ij σ_ij x_i x_j − Σ_i μ_i x_i\n"
                   "s.t. Σ_i c_i x_i ≤ B   (slack-encoded)\n"
                   "     Σ_i x_i = K       (optional)\n"
                   "x_i ∈ {0,1}: hold one position of asset i")
    limitations = "Binary (hold / don't hold) positions; fractional weights need a multi-bit encoding per asset."
    Input = PortfolioInput

    def build_model(self, d: PortfolioInput) -> Model:
        m = Model("portfolio")
        xs = m.binaries([f"hold_{i}" for i in range(len(d.assets))])
        n = len(xs)
        C = d.covariance
        risk = quicksum(C[i][j] * xs[i] * xs[j] for i in range(n) for j in range(n))
        ret = quicksum(d.expected_returns[i] * xs[i] for i in range(n))
        m.minimize(d.risk_aversion * risk - ret)
        m.add_constraint(quicksum(d.costs[i] * xs[i] for i in range(n)) <= d.budget, "budget")
        if d.num_assets is not None:
            m.add_constraint(quicksum(xs) == d.num_assets, "cardinality")
        return m

    def interpret(self, d: PortfolioInput, a):
        sel = [i for i in range(len(d.assets)) if a[f"hold_{i}"]]
        x = np.zeros(len(d.assets)); x[sel] = 1
        C = np.asarray(d.covariance)
        cost = int(sum(d.costs[i] for i in sel))
        return {"selected_assets": [d.assets[i] for i in sel],
                "total_cost": cost, "budget": d.budget, "budget_unit": d.budget_unit,
                "within_budget": cost <= d.budget,
                "expected_return": float(np.dot(d.expected_returns, x)),
                "portfolio_variance": float(x @ C @ x),
                "cardinality_ok": d.num_assets is None or len(sel) == d.num_assets}

    def example(self):
        return {
            "assets": ["INFRA", "BANK", "PHARMA", "IT", "FMCG", "ENERGY"],
            "expected_returns": [0.12, 0.10, 0.08, 0.15, 0.07, 0.11],
            "covariance": [[0.040, 0.012, 0.006, 0.010, 0.004, 0.015],
                           [0.012, 0.030, 0.005, 0.008, 0.006, 0.011],
                           [0.006, 0.005, 0.020, 0.004, 0.003, 0.005],
                           [0.010, 0.008, 0.004, 0.050, 0.005, 0.009],
                           [0.004, 0.006, 0.003, 0.005, 0.015, 0.004],
                           [0.015, 0.011, 0.005, 0.009, 0.004, 0.045]],
            "costs": [3, 2, 2, 4, 1, 3], "budget": 10, "risk_aversion": 0.5,
            "budget_unit": "lakh INR (sample data)"}
