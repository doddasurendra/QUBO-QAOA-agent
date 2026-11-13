"""Standard benchmark problem generators (reproducible with a seed)."""
from __future__ import annotations

from typing import List, Optional, Tuple

import networkx as nx
import numpy as np

from .core.expr import quicksum
from .core.model import Model
from .core.qubo import QUBO


def maxcut(edges: List[Tuple[int, int]], n: int, weights: Optional[List[float]] = None) -> QUBO:
    """Minimise −cut:  Σ w_ij (2 x_i x_j − x_i − x_j)."""
    lin, quad = {}, {}
    for k, (i, j) in enumerate(edges):
        w = 1.0 if weights is None else float(weights[k])
        if i == j:
            raise ValueError("self-loops are not allowed in MaxCut")
        a, b = min(i, j), max(i, j)
        lin[a] = lin.get(a, 0) - w; lin[b] = lin.get(b, 0) - w
        quad[(a, b)] = quad.get((a, b), 0) + 2 * w
    return QUBO([f"v{i}" for i in range(n)], lin, quad)


def random_maxcut(n: int, p: float = 0.5, seed: int = 0) -> Tuple[QUBO, List[Tuple[int, int]]]:
    g = nx.gnp_random_graph(n, p, seed=seed)
    edges = list(g.edges())
    return maxcut(edges, n), edges


def regular_maxcut(n: int, d: int = 3, seed: int = 0):
    g = nx.random_regular_graph(d, n, seed=seed)
    edges = list(g.edges())
    return maxcut(edges, n), edges


def knapsack(values: List[int], weights: List[int], capacity: int) -> Model:
    m = Model("knapsack")
    xs = m.binaries([f"item{i}" for i in range(len(values))])
    m.maximize(quicksum(v * x for v, x in zip(values, xs)))
    m.add_constraint(quicksum(w * x for w, x in zip(weights, xs)) <= capacity, "capacity")
    return m


def random_knapsack(n: int, seed: int = 0) -> Model:
    rng = np.random.default_rng(seed)
    w = rng.integers(1, 10, n).tolist()
    v = rng.integers(1, 15, n).tolist()
    return knapsack(v, w, max(1, int(sum(w) * 0.4)))


def number_partitioning(nums: List[float]) -> QUBO:
    """min (Σ a_i (2x_i − 1))²  — zero iff a perfect partition exists."""
    m = Model("partition")
    xs = m.binaries([f"s{i}" for i in range(len(nums))])
    diff = quicksum(a * (2 * x - 1) for a, x in zip(nums, xs))
    m.minimize(diff * diff)
    return m.compile().qubo


def random_qubo(n: int, density: float = 0.5, seed: int = 0) -> QUBO:
    rng = np.random.default_rng(seed)
    return QUBO([f"x{i}" for i in range(n)], {i: float(rng.normal()) for i in range(n)},
                {(i, j): float(rng.normal()) for i in range(n) for j in range(i + 1, n) if rng.random() < density})


GENERATORS = {
    "maxcut_gnp": lambda n, seed=0, p=0.5: random_maxcut(n, p, seed)[0],
    "maxcut_3regular": lambda n, seed=0: regular_maxcut(n, 3, seed)[0],
    "number_partitioning": lambda n, seed=0: number_partitioning(
        np.random.default_rng(seed).integers(1, 20, n).tolist()),
    "random_qubo": lambda n, seed=0, density=0.5: random_qubo(n, density, seed),
    "knapsack": lambda n, seed=0: random_knapsack(n, seed).compile().qubo,
}
