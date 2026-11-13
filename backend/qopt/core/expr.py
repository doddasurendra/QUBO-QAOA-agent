"""Symbolic quadratic pseudo-Boolean expressions over binary variables.

An :class:`Expr` stores ``const + Σ lin[v]·v + Σ quad[(u,v)]·u·v`` with ``u < v`` (by name order
of insertion index). Because variables are binary, ``v*v == v`` is applied automatically.
Products that would exceed degree 2 raise ``ValueError`` — they are never silently truncated.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Dict, Iterable, Tuple, Union

Number = Union[int, float]


def _key(u: str, v: str) -> Tuple[str, str]:
    return (u, v) if u < v else (v, u)


class Expr:
    __slots__ = ("const", "lin", "quad")

    def __init__(self, const: Number = 0.0, lin: Dict[str, float] | None = None,
                 quad: Dict[Tuple[str, str], float] | None = None):
        self.const = float(const)
        self.lin: Dict[str, float] = dict(lin or {})
        self.quad: Dict[Tuple[str, str], float] = dict(quad or {})

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def var(name: str) -> "Expr":
        return Expr(0.0, {name: 1.0})

    @staticmethod
    def lift(other: Union["Expr", Number]) -> "Expr":
        if isinstance(other, Expr):
            return other
        if isinstance(other, Real):
            return Expr(float(other))
        raise TypeError(f"cannot use {type(other).__name__} in a binary expression")

    def copy(self) -> "Expr":
        return Expr(self.const, self.lin, self.quad)

    @property
    def degree(self) -> int:
        if any(c != 0 for c in self.quad.values()):
            return 2
        if any(c != 0 for c in self.lin.values()):
            return 1
        return 0

    def variables(self) -> set:
        s = set(self.lin)
        for u, v in self.quad:
            s.add(u)
            s.add(v)
        return s

    def is_integral(self, tol: float = 1e-9) -> bool:
        vals = [self.const, *self.lin.values(), *self.quad.values()]
        return all(abs(c - round(c)) <= tol for c in vals)

    def abs_coeff_sum(self) -> float:
        return sum(abs(c) for c in self.lin.values()) + sum(abs(c) for c in self.quad.values())

    def bounds(self) -> Tuple[float, float]:
        """Valid (possibly loose) lower/upper bounds of the expression over {0,1}^n."""
        lo = hi = self.const
        for c in list(self.lin.values()) + list(self.quad.values()):
            if c < 0:
                lo += c
            else:
                hi += c
        return lo, hi

    def evaluate(self, assignment: Dict[str, int]) -> float:
        val = self.const
        for v, c in self.lin.items():
            val += c * assignment[v]
        for (u, v), c in self.quad.items():
            val += c * assignment[u] * assignment[v]
        return val

    def prune(self, tol: float = 0.0) -> "Expr":
        self.lin = {k: c for k, c in self.lin.items() if abs(c) > tol}
        self.quad = {k: c for k, c in self.quad.items() if abs(c) > tol}
        return self

    # ------------------------------------------------------------------ algebra
    def __add__(self, other):
        o = Expr.lift(other)
        r = self.copy()
        r.const += o.const
        for k, c in o.lin.items():
            r.lin[k] = r.lin.get(k, 0.0) + c
        for k, c in o.quad.items():
            r.quad[k] = r.quad.get(k, 0.0) + c
        return r

    __radd__ = __add__

    def __neg__(self):
        return Expr(-self.const, {k: -c for k, c in self.lin.items()},
                    {k: -c for k, c in self.quad.items()})

    def __sub__(self, other):
        return self + (-Expr.lift(other))

    def __rsub__(self, other):
        return Expr.lift(other) + (-self)

    def __mul__(self, other):
        o = Expr.lift(other)
        if self.degree + o.degree > 2:
            raise ValueError("product exceeds degree 2; QUBO models are quadratic. "
                             "Introduce auxiliary variables explicitly.")
        r = Expr(self.const * o.const)
        # const * linear / quad
        for k, c in self.lin.items():
            r.lin[k] = r.lin.get(k, 0.0) + c * o.const
        for k, c in o.lin.items():
            r.lin[k] = r.lin.get(k, 0.0) + c * self.const
        for k, c in self.quad.items():
            r.quad[k] = r.quad.get(k, 0.0) + c * o.const
        for k, c in o.quad.items():
            r.quad[k] = r.quad.get(k, 0.0) + c * self.const
        # linear * linear (x*x = x for binaries)
        for u, cu in self.lin.items():
            for v, cv in o.lin.items():
                if u == v:
                    r.lin[u] = r.lin.get(u, 0.0) + cu * cv
                else:
                    k = _key(u, v)
                    r.quad[k] = r.quad.get(k, 0.0) + cu * cv
        return r

    __rmul__ = __mul__

    def __truediv__(self, other):
        if not isinstance(other, Real):
            raise TypeError("can only divide by a number")
        return self * (1.0 / float(other))

    def __pow__(self, p):
        if p == 1:
            return self.copy()
        if p == 2:
            return self * self
        raise ValueError("only powers 1 and 2 are supported")

    # comparisons build constraint objects (not booleans)
    def __eq__(self, other):  # type: ignore[override]
        return ConstraintSpec(self - Expr.lift(other), "==")

    def __le__(self, other):
        return ConstraintSpec(self - Expr.lift(other), "<=")

    def __ge__(self, other):
        return ConstraintSpec(self - Expr.lift(other), ">=")

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self):
        parts = [f"{self.const:g}"] if self.const else []
        parts += [f"{c:g}*{v}" for v, c in self.lin.items()]
        parts += [f"{c:g}*{u}*{v}" for (u, v), c in self.quad.items()]
        return "Expr(" + (" + ".join(parts) or "0") + ")"


@dataclass
class ConstraintSpec:
    """``lhs (sense) 0`` where lhs already has the right-hand side moved over."""
    lhs: Expr
    sense: str  # '==', '<=', '>='


def quicksum(items: Iterable[Union[Expr, Number]]) -> Expr:
    acc = Expr()
    for it in items:
        o = Expr.lift(it)
        acc.const += o.const
        for k, c in o.lin.items():
            acc.lin[k] = acc.lin.get(k, 0.0) + c
        for k, c in o.quad.items():
            acc.quad[k] = acc.quad.get(k, 0.0) + c
    return acc
