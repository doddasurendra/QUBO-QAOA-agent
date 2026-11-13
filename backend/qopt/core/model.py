"""Constrained binary model → QUBO compiler.

``Model`` holds an objective (degree ≤ 2) plus linear/quadratic constraints over binary
decision variables. ``compile()`` produces a :class:`CompiledModel` holding the penalised
QUBO, the slack variables that were introduced, the penalty weights used and the original
constraints, so any assignment can be checked against the *original* problem.
Constraints are never discarded: every one is either penalised or the compile fails.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .expr import ConstraintSpec, Expr, quicksum
from .qubo import QUBO


@dataclass
class Constraint:
    label: str
    lhs: Expr          # constraint is  lhs (sense) 0
    sense: str         # '==', '<=', '>='
    penalty: Optional[float] = None   # None → automatic
    resolution: Optional[float] = None  # for non-integral inequalities
    kind: str = "general"  # 'one_hot', 'general' (used by constraint-preserving mixers)

    def violation(self, assignment: Dict[str, int]) -> float:
        v = self.lhs.evaluate(assignment)
        if self.sense == "==":
            return abs(v)
        if self.sense == "<=":
            return max(0.0, v)
        return max(0.0, -v)

    def describe(self) -> str:
        return f"{self.label}: {self.lhs!r} {self.sense} 0"


@dataclass
class SlackInfo:
    constraint: str
    variables: List[str]
    weights: List[float]
    max_slack: float


class Model:
    def __init__(self, name: str = "model"):
        self.name = name
        self.variables: List[str] = []
        self._vset: set = set()
        self.objective = Expr()
        self.sense = "min"
        self.constraints: List[Constraint] = []
        self.metadata: dict = {}

    # ----------------------------------------------------------- variables
    def binary(self, name: str) -> Expr:
        if not name or any(ch.isspace() for ch in name):
            raise ValueError(f"invalid variable name {name!r}")
        if name in self._vset:
            raise ValueError(f"variable {name!r} already defined")
        if name.startswith("_slack"):
            raise ValueError("names starting with '_slack' are reserved")
        self.variables.append(name)
        self._vset.add(name)
        return Expr.var(name)

    def binaries(self, names: Sequence[str]) -> List[Expr]:
        return [self.binary(n) for n in names]

    def var(self, name: str) -> Expr:
        if name not in self._vset:
            raise KeyError(f"unknown variable {name!r}")
        return Expr.var(name)

    # ----------------------------------------------------------- objective
    def minimize(self, expr) -> None:
        self._check(Expr.lift(expr))
        self.objective = Expr.lift(expr).copy()
        self.sense = "min"

    def maximize(self, expr) -> None:
        self._check(Expr.lift(expr))
        self.objective = Expr.lift(expr).copy()
        self.sense = "max"

    # ----------------------------------------------------------- constraints
    def add_constraint(self, spec: ConstraintSpec, label: Optional[str] = None,
                       penalty: Optional[float] = None, resolution: Optional[float] = None,
                       kind: str = "general") -> Constraint:
        if not isinstance(spec, ConstraintSpec):
            raise TypeError("use expressions with ==, <= or >= to build a constraint")
        self._check(spec.lhs)
        if spec.sense != "==" and spec.lhs.degree > 1:
            raise ValueError("quadratic inequality constraints are not supported; "
                             "linearise with auxiliary variables first")
        if penalty is not None and penalty <= 0:
            raise ValueError("penalty weight must be positive")
        label = label or f"c{len(self.constraints)}"
        if any(c.label == label for c in self.constraints):
            raise ValueError(f"duplicate constraint label {label!r}")
        c = Constraint(label, spec.lhs.copy(), spec.sense, penalty, resolution, kind)
        self.constraints.append(c)
        return c

    def add_one_hot(self, names: Sequence[str], label: Optional[str] = None,
                    penalty: Optional[float] = None) -> Constraint:
        return self.add_constraint(quicksum(self.var(n) for n in names) == 1, label, penalty,
                                   kind="one_hot")

    def _check(self, e: Expr):
        unknown = e.variables() - self._vset
        if unknown:
            raise ValueError(f"expression uses undeclared variables: {sorted(unknown)}")

    # ----------------------------------------------------------- compile
    def auto_penalty(self) -> float:
        """P = Σ|objective coefficients| + 1  ≥  (max f − min f) + 1.

        For integer-coefficient constraints a violation adds ≥ P·1 energy, so every
        infeasible assignment is worse than every feasible one."""
        return self.objective.abs_coeff_sum() + 1.0

    def compile(self, penalty_scale: float = 1.0) -> "CompiledModel":
        obj = self.objective if self.sense == "min" else -self.objective
        P_auto = self.auto_penalty() * penalty_scale
        total = obj.copy()
        slack_vars: List[str] = []
        slacks: List[SlackInfo] = []
        penalties: Dict[str, float] = {}
        warnings: List[str] = []

        for c in self.constraints:
            lhs = c.lhs.copy()
            if c.sense == ">=":
                lhs = -lhs  # lhs >= 0  ⇔  -lhs <= 0
            if c.sense != "==":
                lhs, info, warn = _add_slack(lhs, c, len(slack_vars))
                if info is None:  # constraint always satisfied
                    warnings.append(warn)
                    penalties[c.label] = 0.0
                    continue
                if warn:
                    warnings.append(warn)
                slack_vars += info.variables
                slacks.append(info)
            else:
                if not lhs.is_integral():
                    warnings.append(
                        f"constraint {c.label!r} has non-integer coefficients; the automatic "
                        "penalty bound assumes violations ≥ 1 — verify feasibility of results "
                        "(always checked by evaluate())")
            lo, hi = lhs.bounds()
            if c.sense == "==" and (lo > 0 or hi < 0):
                raise ValueError(f"constraint {c.label!r} is infeasible for every assignment "
                                 f"(lhs range [{lo:g}, {hi:g}] excludes 0)")
            P = c.penalty if c.penalty is not None else P_auto
            penalties[c.label] = P
            if lhs.degree == 2:
                # (lhs)^2 would be degree 4. If every coefficient is ≥ 0 then lhs ≥ 0 on {0,1}^n,
                # so P·lhs is zero exactly when the constraint holds and ≥ P·min|coef| otherwise.
                if lhs.const < 0 or any(v < 0 for v in list(lhs.lin.values()) + list(lhs.quad.values())):
                    raise ValueError(f"quadratic equality {c.label!r} must have non-negative coefficients "
                                     "and right-hand side 0 (e.g. x*y == 0); otherwise linearise it")
                if not lhs.is_integral():
                    warnings.append(f"quadratic constraint {c.label!r} has non-integer coefficients")
                total = total + P * lhs
            else:
                total = total + P * (lhs * lhs)

        names = list(self.variables) + slack_vars
        qubo = QUBO.from_expr(total.prune(), names)
        return CompiledModel(self, qubo, list(self.variables), slack_vars, slacks, penalties,
                             warnings)

    # ----------------------------------------------------------- serialization
    def to_spec(self) -> dict:
        def e2d(e: Expr) -> dict:
            return {"constant": e.const, "linear": dict(e.lin),
                    "quadratic": [[u, v, c] for (u, v), c in e.quad.items()]}
        return {
            "name": self.name, "variables": list(self.variables), "sense": self.sense,
            "objective": e2d(self.objective),
            "constraints": [{"label": c.label, "lhs": e2d(c.lhs), "sense": c.sense, "rhs": 0.0,
                             "penalty": c.penalty, "resolution": c.resolution, "kind": c.kind}
                            for c in self.constraints],
            "metadata": self.metadata,
        }

    @classmethod
    def from_spec(cls, spec: dict) -> "Model":
        """Build from the JSON spec used by the API and the AI formulation agent.

        ``{"variables": [...], "sense": "min"|"max",
           "objective": {"constant": c, "linear": {v: c}, "quadratic": [[u, v, c], ...]},
           "constraints": [{"label", "lhs": {...}, "sense": "==|<=|>=", "rhs": r,
                            "penalty"?: P, "kind"?: "one_hot"}]}``"""
        m = cls(spec.get("name", "model"))
        for v in spec["variables"]:
            m.binary(str(v))

        def d2e(d: dict) -> Expr:
            e = Expr(float(d.get("constant", 0.0)))
            for v, c in (d.get("linear") or {}).items():
                e = e + float(c) * m.var(v)
            for u, v, c in d.get("quadratic") or []:
                e = e + float(c) * (m.var(u) * m.var(v))
            return e

        obj = d2e(spec.get("objective") or {})
        if spec.get("sense", "min") == "max":
            m.maximize(obj)
        else:
            m.minimize(obj)
        for c in spec.get("constraints") or []:
            lhs = d2e(c["lhs"]) - float(c.get("rhs", 0.0))
            sense = c["sense"]
            if sense not in ("==", "<=", ">="):
                raise ValueError(f"invalid constraint sense {sense!r}")
            m.add_constraint(ConstraintSpec(lhs, sense), c.get("label"), c.get("penalty"),
                             c.get("resolution"), c.get("kind", "general"))
        m.metadata = dict(spec.get("metadata") or {})
        return m


def _binary_expansion_weights(max_value: int) -> List[int]:
    """Weights w with Σ w_k b_k able to represent exactly {0, …, max_value}."""
    weights, total, p = [], 0, 1
    while total + p <= max_value:
        weights.append(p)
        total += p
        p *= 2
    if total < max_value:
        weights.append(max_value - total)
    return weights


def _add_slack(lhs: Expr, c: Constraint, start: int):
    """Turn ``lhs <= 0`` into ``lhs + s == 0`` with s ∈ [0, -min(lhs)] encoded in binary."""
    warn = ""
    scale = 1.0
    if not lhs.is_integral():
        if c.resolution is None:
            raise ValueError(
                f"inequality {c.label!r} has non-integer coefficients; supply 'resolution' "
                "(the slack step size) so the discretisation is explicit")
        scale = 1.0 / c.resolution
        scaled = lhs * scale
        rounded = Expr(round(scaled.const), {k: round(v) for k, v in scaled.lin.items()})
        err = max([abs(scaled.const - rounded.const)] +
                  [abs(v - rounded.lin[k]) for k, v in scaled.lin.items()])
        warn = (f"inequality {c.label!r} scaled by 1/{c.resolution:g} and rounded to integers "
                f"(max coefficient rounding error {err:.3g} resolution units)")
        lhs = rounded
    lo, hi = lhs.bounds()
    if hi <= 0:
        return lhs, None, f"inequality {c.label!r} is satisfied by every assignment; no penalty added"
    if lo > 0:
        raise ValueError(f"inequality {c.label!r} cannot be satisfied by any assignment")
    max_slack = int(math.floor(-lo + 1e-9))
    weights = _binary_expansion_weights(max_slack)
    names = [f"_slack{start + k}_{c.label}" for k in range(len(weights))]
    s = quicksum(w * Expr.var(n) for w, n in zip(weights, names))
    return lhs + s, SlackInfo(c.label, names, [float(w) for w in weights], float(max_slack)), warn


@dataclass
class SolutionReport:
    assignment: Dict[str, int]
    objective: float                 # in the user's sense (max problems reported as max)
    qubo_energy: float
    feasible: bool
    violations: Dict[str, float]
    bitstring: str                   # decision variables only, in variable order

    def to_dict(self) -> dict:
        return {"assignment": self.assignment, "objective": self.objective,
                "qubo_energy": self.qubo_energy, "feasible": self.feasible,
                "violations": self.violations, "bitstring": self.bitstring,
                "bit_order": "decision variables in model order (x0 first)"}


@dataclass
class CompiledModel:
    model: Model
    qubo: QUBO
    decision_variables: List[str]
    slack_variables: List[str]
    slacks: List[SlackInfo]
    penalties: Dict[str, float]
    warnings: List[str] = field(default_factory=list)

    @property
    def num_decision(self) -> int:
        return len(self.decision_variables)

    def decision_assignment(self, x) -> Dict[str, int]:
        x = np.asarray(x).astype(int)
        if x.shape[0] == self.qubo.num_variables:
            x = x[: self.num_decision]
        if x.shape[0] != self.num_decision:
            raise ValueError("assignment length matches neither decision nor QUBO variables")
        return {v: int(b) for v, b in zip(self.decision_variables, x)}

    def best_slack_completion(self, decision_x) -> np.ndarray:
        """Given decision bits, choose slack bits minimising the QUBO energy.

        Each constraint's slack block only appears in that constraint's penalty, so the
        optimal slack value is the clamp of −lhs to [0, max_slack]; a greedy binary
        decomposition of that value is exact because weights are 1,2,4,…,remainder."""
        d = self.decision_assignment(decision_x)
        full = dict(d)
        for info in self.slacks:
            c = next(cc for cc in self.model.constraints if cc.label == info.constraint)
            lhs = c.lhs if c.sense == "<=" else -c.lhs
            if c.resolution is not None and not lhs.is_integral():
                lhs = lhs * (1.0 / c.resolution)
            target = int(round(min(max(-lhs.evaluate(d), 0.0), info.max_slack)))
            for n, w in sorted(zip(info.variables, info.weights), key=lambda t: -t[1]):
                bit = 1 if w <= target else 0
                target -= int(w) * bit
                full[n] = bit
        return np.array([full[v] for v in self.qubo.variables], dtype=int)

    def evaluate(self, x) -> SolutionReport:
        x = np.asarray(x).astype(int)
        if x.shape[0] == self.num_decision and self.slack_variables:
            x = self.best_slack_completion(x)
        d = self.decision_assignment(x)
        obj = self.model.objective.evaluate(d)
        viol = {c.label: c.violation(d) for c in self.model.constraints}
        feasible = all(v <= 1e-9 for v in viol.values())
        return SolutionReport(d, float(obj), self.qubo.energy(x), feasible,
                              {k: float(v) for k, v in viol.items() if v > 1e-9},
                              "".join(str(d[v]) for v in self.decision_variables))

    def one_hot_groups(self) -> List[List[int]]:
        """Disjoint one-hot groups (indices into qubo variables), for XY mixers."""
        idx = self.qubo.index
        groups, used = [], set()
        for c in self.model.constraints:
            if c.kind != "one_hot":
                continue
            g = [idx[v] for v in c.lhs.lin]
            if used.intersection(g):
                return []  # overlapping groups are not supported by the XY mixer
            used.update(g)
            groups.append(sorted(g))
        return groups

    def summary(self) -> dict:
        return {
            "name": self.model.name,
            "sense": self.model.sense,
            "num_decision_variables": self.num_decision,
            "num_slack_variables": len(self.slack_variables),
            "num_constraints": len(self.model.constraints),
            "penalties": self.penalties,
            "warnings": self.warnings,
            "qubo": self.qubo.stats(),
            "constraints": [c.describe() for c in self.model.constraints],
            "slacks": [s.__dict__ for s in self.slacks],
        }
