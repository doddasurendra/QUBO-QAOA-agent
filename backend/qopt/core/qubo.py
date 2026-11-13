"""QUBO and Ising representations with exact, tested conversions.

Conventions (see docs/ARCHITECTURE.md §2):

* QUBO energy  ``E(x) = offset + Σ a_i x_i + Σ_{i<j} b_ij x_i x_j``
* Matrix form  upper-triangular ``Q`` (``Q_ii = a_i``, ``Q_ij = b_ij``), ``E = xᵀQx + offset``
* Spin map     ``x_i = (1 - z_i) / 2`` so bit 0 ↔ z=+1 ↔ |0⟩
* Ising energy ``H(z) = c + Σ h_i z_i + Σ_{i<j} J_ij z_i z_j``
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy import sparse

from .expr import Expr


@dataclass
class QUBO:
    variables: List[str]
    linear: Dict[int, float] = field(default_factory=dict)
    quadratic: Dict[Tuple[int, int], float] = field(default_factory=dict)  # keys i<j
    offset: float = 0.0

    def __post_init__(self):
        if len(set(self.variables)) != len(self.variables):
            raise ValueError("duplicate variable names")
        n = len(self.variables)
        clean: Dict[Tuple[int, int], float] = {}
        for (i, j), c in self.quadratic.items():
            if not (0 <= i < n and 0 <= j < n):
                raise ValueError(f"quadratic index {(i, j)} out of range")
            if i == j:  # x_i * x_i == x_i
                self.linear[i] = self.linear.get(i, 0.0) + float(c)
                continue
            k = (i, j) if i < j else (j, i)
            clean[k] = clean.get(k, 0.0) + float(c)
        self.quadratic = clean
        for i in self.linear:
            if not 0 <= i < n:
                raise ValueError(f"linear index {i} out of range")
        self.linear = {int(i): float(c) for i, c in self.linear.items()}
        self.offset = float(self.offset)

    # ------------------------------------------------------------- construction
    @property
    def num_variables(self) -> int:
        return len(self.variables)

    @property
    def index(self) -> Dict[str, int]:
        return {v: i for i, v in enumerate(self.variables)}

    @classmethod
    def from_expr(cls, expr: Expr, variables: Optional[Sequence[str]] = None) -> "QUBO":
        names = list(variables) if variables is not None else sorted(expr.variables())
        missing = expr.variables() - set(names)
        if missing:
            raise ValueError(f"expression uses undeclared variables: {sorted(missing)}")
        idx = {v: i for i, v in enumerate(names)}
        lin = {idx[v]: c for v, c in expr.lin.items() if c != 0}
        quad = {}
        for (u, v), c in expr.quad.items():
            if c == 0:
                continue
            i, j = idx[u], idx[v]
            k = (i, j) if i < j else (j, i)
            quad[k] = quad.get(k, 0.0) + c
        return cls(names, lin, quad, expr.const)

    @classmethod
    def from_matrix(cls, Q, offset: float = 0.0, variables: Optional[Sequence[str]] = None,
                    convention: str = "auto") -> "QUBO":
        """Build from a matrix. ``convention``: 'upper' (E = xᵀQx with Q upper), 'symmetric'
        (E = xᵀQx with Q symmetric) or 'auto' (any square matrix; E = xᵀQx always holds)."""
        M = Q.toarray() if sparse.issparse(Q) else np.asarray(Q, dtype=float)
        if M.ndim != 2 or M.shape[0] != M.shape[1]:
            raise ValueError("QUBO matrix must be square")
        if convention == "upper" and np.any(np.tril(M, -1) != 0):
            raise ValueError("matrix declared 'upper' has entries below the diagonal")
        if convention == "symmetric" and not np.allclose(M, M.T):
            raise ValueError("matrix declared 'symmetric' is not symmetric")
        n = M.shape[0]
        names = list(variables) if variables is not None else [f"x{i}" for i in range(n)]
        if len(names) != n:
            raise ValueError("variable name count does not match matrix size")
        # xᵀMx = Σ M_ii x_i + Σ_{i<j} (M_ij + M_ji) x_i x_j   for any square M
        lin = {i: float(M[i, i]) for i in range(n) if M[i, i] != 0}
        U = np.triu(M, 1) + np.tril(M, -1).T
        rows, cols = np.nonzero(U)
        quad = {(int(i), int(j)): float(U[i, j]) for i, j in zip(rows, cols)}
        return cls(names, lin, quad, offset)

    # ------------------------------------------------------------- matrices
    def linear_vector(self) -> np.ndarray:
        a = np.zeros(self.num_variables)
        for i, c in self.linear.items():
            a[i] = c
        return a

    def to_matrix(self, convention: str = "upper") -> np.ndarray:
        n = self.num_variables
        Q = np.zeros((n, n))
        for i, c in self.linear.items():
            Q[i, i] = c
        for (i, j), c in self.quadratic.items():
            if convention == "upper":
                Q[i, j] += c
            elif convention == "symmetric":
                Q[i, j] += c / 2
                Q[j, i] += c / 2
            else:
                raise ValueError("convention must be 'upper' or 'symmetric'")
        return Q

    def to_sparse(self, convention: str = "upper") -> sparse.csr_matrix:
        n = self.num_variables
        rows, cols, vals = [], [], []
        for i, c in self.linear.items():
            rows.append(i); cols.append(i); vals.append(c)
        for (i, j), c in self.quadratic.items():
            if convention == "upper":
                rows.append(i); cols.append(j); vals.append(c)
            else:
                rows += [i, j]; cols += [j, i]; vals += [c / 2, c / 2]
        return sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))

    def strict_upper(self) -> np.ndarray:
        n = self.num_variables
        B = np.zeros((n, n))
        for (i, j), c in self.quadratic.items():
            B[i, j] = c
        return B

    # ------------------------------------------------------------- evaluation
    def energy(self, x) -> float:
        x = self._as_vector(x)
        e = self.offset
        for i, c in self.linear.items():
            e += c * x[i]
        for (i, j), c in self.quadratic.items():
            e += c * x[i] * x[j]
        return float(e)

    def energies(self, X: np.ndarray) -> np.ndarray:
        """Vectorised energies for a (m, n) 0/1 array."""
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != self.num_variables:
            raise ValueError("X must have shape (m, n)")
        if not np.all((X == 0) | (X == 1)):
            raise ValueError("assignments must be binary (0/1)")
        a = self.linear_vector()
        e = self.offset + X @ a
        if self.quadratic:
            e = e + _quad_part(X, self.to_sparse_strict())
        return e

    def to_sparse_strict(self) -> sparse.csr_matrix:
        n = self.num_variables
        if not self.quadratic:
            return sparse.csr_matrix((n, n))
        ij = np.array(list(self.quadratic.keys()))
        v = np.array(list(self.quadratic.values()))
        return sparse.csr_matrix((v, (ij[:, 0], ij[:, 1])), shape=(n, n))

    def _as_vector(self, x) -> np.ndarray:
        if isinstance(x, dict):
            idx = self.index
            vec = np.zeros(self.num_variables)
            for k, val in x.items():
                vec[idx[k]] = val
            x = vec
        elif isinstance(x, str):
            x = np.array([int(ch) for ch in x])
        x = np.asarray(x, dtype=float)
        if x.shape != (self.num_variables,):
            raise ValueError(f"assignment must have length {self.num_variables}")
        if not np.all((x == 0) | (x == 1)):
            raise ValueError("assignment must be binary (0/1)")
        return x

    # ------------------------------------------------------------- stats / utils
    def density(self) -> float:
        n = self.num_variables
        return 0.0 if n < 2 else len(self.quadratic) / (n * (n - 1) / 2)

    def max_abs_coefficient(self) -> float:
        vals = [abs(c) for c in self.linear.values()] + [abs(c) for c in self.quadratic.values()]
        return max(vals) if vals else 0.0

    def scaled(self, factor: float) -> "QUBO":
        """Positive rescaling preserves the argmin (energies scale by ``factor``)."""
        if factor <= 0:
            raise ValueError("scale factor must be positive (negative would flip min/max)")
        return QUBO(list(self.variables), {i: c * factor for i, c in self.linear.items()},
                    {k: c * factor for k, c in self.quadratic.items()}, self.offset * factor)

    def normalized(self) -> Tuple["QUBO", float]:
        """Scale so the largest |coefficient| is 1. Returns (qubo, factor)."""
        m = self.max_abs_coefficient()
        if m == 0:
            return self, 1.0
        return self.scaled(1.0 / m), 1.0 / m

    def adjacency(self) -> Dict[int, List[Tuple[int, float]]]:
        adj: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(self.num_variables)}
        for (i, j), c in self.quadratic.items():
            adj[i].append((j, c))
            adj[j].append((i, c))
        return adj

    def stats(self) -> dict:
        return {
            "num_variables": self.num_variables,
            "num_linear_terms": len(self.linear),
            "num_quadratic_terms": len(self.quadratic),
            "density": self.density(),
            "max_abs_coefficient": self.max_abs_coefficient(),
            "offset": self.offset,
        }

    # ------------------------------------------------------------- serialization
    def to_dict(self) -> dict:
        return {
            "format": "qopt.qubo/v1",
            "energy_convention": "E(x) = offset + sum_i linear[i] x_i + sum_{i<j} quadratic[i,j] x_i x_j",
            "variables": list(self.variables),
            "linear": {str(i): c for i, c in sorted(self.linear.items())},
            "quadratic": [[i, j, c] for (i, j), c in sorted(self.quadratic.items())],
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QUBO":
        if d.get("format", "qopt.qubo/v1") != "qopt.qubo/v1":
            raise ValueError(f"unsupported QUBO format {d.get('format')}")
        lin = {int(i): float(c) for i, c in d.get("linear", {}).items()}
        quad = {}
        for i, j, c in d.get("quadratic", []):
            k = (int(i), int(j)) if int(i) < int(j) else (int(j), int(i))
            quad[k] = quad.get(k, 0.0) + float(c)
        return cls(list(d["variables"]), lin, quad, float(d.get("offset", 0.0)))

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> "QUBO":
        return cls.from_dict(json.loads(s))

    # ------------------------------------------------------------- Ising
    def to_ising(self) -> "Ising":
        n = self.num_variables
        h = np.zeros(n)
        c = self.offset
        for i, a in self.linear.items():
            h[i] += -a / 2
            c += a / 2
        J: Dict[Tuple[int, int], float] = {}
        for (i, j), b in self.quadratic.items():
            J[(i, j)] = b / 4
            h[i] += -b / 4
            h[j] += -b / 4
            c += b / 4
        return Ising(list(self.variables), {i: float(v) for i, v in enumerate(h) if v != 0}, J, c)


def _quad_part(X: np.ndarray, B: sparse.csr_matrix) -> np.ndarray:
    # Σ_{i<j} b_ij x_i x_j  for each row of X  ==  rowsum((X @ B) ∘ X)
    XB = np.asarray(B.T.dot(X.T).T)  # (m, n) == X @ B
    return np.einsum("ij,ij->i", XB, X)


@dataclass
class Ising:
    variables: List[str]
    h: Dict[int, float] = field(default_factory=dict)
    J: Dict[Tuple[int, int], float] = field(default_factory=dict)  # keys i<j
    offset: float = 0.0

    def __post_init__(self):
        clean = {}
        for (i, j), c in self.J.items():
            if i == j:  # z_i^2 = 1
                self.offset += c
                continue
            k = (i, j) if i < j else (j, i)
            clean[k] = clean.get(k, 0.0) + float(c)
        self.J = clean

    @property
    def num_variables(self) -> int:
        return len(self.variables)

    def energy(self, z) -> float:
        z = np.asarray(z, dtype=float)
        if not np.all(np.abs(z) == 1):
            raise ValueError("spins must be ±1")
        e = self.offset + sum(c * z[i] for i, c in self.h.items())
        e += sum(c * z[i] * z[j] for (i, j), c in self.J.items())
        return float(e)

    def energies(self, Z: np.ndarray) -> np.ndarray:
        Z = np.asarray(Z, dtype=float)
        e = np.full(Z.shape[0], self.offset)
        for i, c in self.h.items():
            e += c * Z[:, i]
        for (i, j), c in self.J.items():
            e += c * Z[:, i] * Z[:, j]
        return e

    def to_qubo(self) -> QUBO:
        # z_i = 1 - 2 x_i
        lin: Dict[int, float] = {}
        quad: Dict[Tuple[int, int], float] = {}
        c = self.offset
        for i, hv in self.h.items():
            c += hv
            lin[i] = lin.get(i, 0.0) - 2 * hv
        for (i, j), Jv in self.J.items():
            c += Jv
            lin[i] = lin.get(i, 0.0) - 2 * Jv
            lin[j] = lin.get(j, 0.0) - 2 * Jv
            quad[(i, j)] = quad.get((i, j), 0.0) + 4 * Jv
        return QUBO(list(self.variables), {k: v for k, v in lin.items() if v != 0},
                    {k: v for k, v in quad.items() if v != 0}, c)

    def to_pauli_terms(self) -> List[Tuple[str, float]]:
        """Pauli strings in Qiskit order (rightmost character = qubit 0)."""
        n = self.num_variables
        terms = []
        for i, c in sorted(self.h.items()):
            s = ["I"] * n
            s[n - 1 - i] = "Z"
            terms.append(("".join(s), c))
        for (i, j), c in sorted(self.J.items()):
            s = ["I"] * n
            s[n - 1 - i] = "Z"
            s[n - 1 - j] = "Z"
            terms.append(("".join(s), c))
        return terms

    def to_dict(self) -> dict:
        return {
            "format": "qopt.ising/v1",
            "energy_convention": "H(z) = offset + sum h_i z_i + sum_{i<j} J_ij z_i z_j ; x_i = (1 - z_i)/2",
            "variables": list(self.variables),
            "h": {str(i): c for i, c in sorted(self.h.items())},
            "J": [[i, j, c] for (i, j), c in sorted(self.J.items())],
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Ising":
        return cls(list(d["variables"]), {int(i): float(c) for i, c in d.get("h", {}).items()},
                   {(int(i), int(j)): float(c) for i, j, c in d.get("J", [])}, float(d.get("offset", 0.0)))


def bits_to_spins(x) -> np.ndarray:
    return 1 - 2 * np.asarray(x, dtype=int)


def spins_to_bits(z) -> np.ndarray:
    return ((1 - np.asarray(z, dtype=int)) // 2).astype(int)


def all_assignments(n: int, start: int = 0, stop: Optional[int] = None) -> np.ndarray:
    """Rows are basis states k in [start, stop); column i is bit i of k (little-endian)."""
    stop = (1 << n) if stop is None else stop
    k = np.arange(start, stop, dtype=np.int64)
    return ((k[:, None] >> np.arange(n, dtype=np.int64)[None, :]) & 1).astype(np.int8)
