"""Telecom: spectrum (channel) allocation and capacity-aware network routing."""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


# ----------------------------------------------------------------------------- spectrum allocation
class SpectrumInput(BaseModel):
    transmitters: List[str] = Field(min_length=2, max_length=10)
    channels: List[str] = Field(min_length=2, max_length=5, description="ordered by frequency")
    interference: List[List[float]] = Field(description="symmetric pairwise co-channel interference weight (≥ 0)")
    adjacent_channel_factor: float = Field(default=0.3, ge=0, le=1)
    channel_cost: Optional[List[List[float]]] = Field(default=None, description="transmitter×channel cost")

    @model_validator(mode="after")
    def _check(self):
        n, c = len(self.transmitters), len(self.channels)
        I = np.asarray(self.interference, float)
        if I.shape != (n, n) or not np.allclose(I, I.T) or I.min() < 0:
            raise ValueError("interference must be a symmetric non-negative n×n matrix")
        if self.channel_cost is not None and (len(self.channel_cost) != n or any(len(r) != c for r in self.channel_cost)):
            raise ValueError("channel_cost must be transmitters×channels")
        return self


def spectrum_interference(d: SpectrumInput, ch: List[int]) -> float:
    tot = 0.0
    for i in range(len(ch)):
        for j in range(i + 1, len(ch)):
            if ch[i] == ch[j]:
                tot += d.interference[i][j]
            elif abs(ch[i] - ch[j]) == 1:
                tot += d.adjacent_channel_factor * d.interference[i][j]
    return tot


class SpectrumAllocation(IndustryProblem):
    key = "telecom.spectrum_allocation"
    industry = "telecommunications"
    title = "Spectrum / channel allocation"
    description = "Assign one channel to each transmitter minimising co-channel and adjacent-channel interference."
    formulation = ("min  Σ_{i<j} I_ij [ Σ_c x_ic x_jc + α Σ_c (x_ic x_j,c+1 + x_i,c+1 x_jc) ] + Σ_ic k_ic x_ic\n"
                   "s.t. Σ_c x_ic = 1   ∀ transmitters (one-hot; XY mixer compatible)")
    Input = SpectrumInput

    def build_model(self, d: SpectrumInput) -> Model:
        m = Model("spectrum_allocation")
        n, C = len(d.transmitters), len(d.channels)
        X = [[m.binary(f"ch_{i}_{c}") for c in range(C)] for i in range(n)]
        terms = []
        for i in range(n):
            for j in range(i + 1, n):
                w = d.interference[i][j]
                if w == 0:
                    continue
                terms += [w * X[i][c] * X[j][c] for c in range(C)]
                if d.adjacent_channel_factor:
                    terms += [w * d.adjacent_channel_factor * (X[i][c] * X[j][c + 1] + X[i][c + 1] * X[j][c])
                              for c in range(C - 1)]
        cost = quicksum(d.channel_cost[i][c] * X[i][c] for i in range(n) for c in range(C)) if d.channel_cost else 0
        m.minimize(quicksum(terms) + cost)
        for i in range(n):
            m.add_one_hot([f"ch_{i}_{c}" for c in range(C)], f"tx_{i}")
        return m

    def interpret(self, d: SpectrumInput, a):
        n, C = len(d.transmitters), len(d.channels)
        ch = [[c for c in range(C) if a[f"ch_{i}_{c}"]] for i in range(n)]
        ok = all(len(c) == 1 for c in ch)
        out = {"assignment": {d.transmitters[i]: [d.channels[c] for c in ch[i]] for i in range(n)},
               "one_channel_each_ok": ok}
        if ok:
            flat = [c[0] for c in ch]
            out["total_interference"] = spectrum_interference(d, flat)
            out["co_channel_conflicts"] = [[d.transmitters[i], d.transmitters[j]] for i in range(n)
                                           for j in range(i + 1, n) if flat[i] == flat[j] and d.interference[i][j] > 0]
        return out

    def example(self):
        n = 5
        I = [[0.0] * n for _ in range(n)]
        for i, j, w in [(0, 1, 1.0), (1, 2, 0.8), (2, 3, 1.0), (3, 4, 0.6), (0, 4, 0.9), (0, 2, 0.3)]:
            I[i][j] = I[j][i] = w
        return {"transmitters": ["cell-A", "cell-B", "cell-C", "cell-D", "cell-E"],
                "channels": ["3.50GHz", "3.52GHz", "3.54GHz"], "interference": I, "adjacent_channel_factor": 0.3}


# ----------------------------------------------------------------------------- network routing
class Demand(BaseModel):
    name: str
    volume: int = Field(ge=1)
    paths: List[List[int]] = Field(min_length=1, max_length=5, description="candidate paths as node-index sequences")


class RoutingInput(BaseModel):
    nodes: List[str] = Field(min_length=2, max_length=20)
    links: List[Tuple[int, int]] = Field(min_length=1, description="undirected links (node indices)")
    link_capacity: List[int]
    link_latency: Optional[List[float]] = None
    demands: List[Demand] = Field(min_length=1, max_length=8)
    congestion_weight: float = Field(default=0.5, ge=0)

    @model_validator(mode="after")
    def _check(self):
        L = len(self.links)
        if len(self.link_capacity) != L or any(c <= 0 for c in self.link_capacity):
            raise ValueError("one positive capacity per link")
        if self.link_latency is not None and (len(self.link_latency) != L or min(self.link_latency) < 0):
            raise ValueError("one non-negative latency per link")
        idx = self.link_index()
        for d in self.demands:
            ends = {(p[0], p[-1]) for p in d.paths}
            if len(ends) != 1:
                raise ValueError(f"demand {d.name}: all paths must share the same source and destination")
            for p in d.paths:
                if len(p) < 2 or len(set(p)) != len(p):
                    raise ValueError(f"demand {d.name}: paths need ≥ 2 distinct nodes and no loops")
                for u, v in zip(p, p[1:]):
                    if (min(u, v), max(u, v)) not in idx:
                        raise ValueError(f"demand {d.name}: hop {self.nodes[u]}–{self.nodes[v]} is not a link")
        return self

    def link_index(self):
        return {(min(u, v), max(u, v)): k for k, (u, v) in enumerate(self.links)}

    def path_links(self, p: List[int]) -> List[int]:
        idx = self.link_index()
        return [idx[(min(u, v), max(u, v))] for u, v in zip(p, p[1:])]

    def latency(self, k: int) -> float:
        return self.link_latency[k] if self.link_latency else 1.0


class NetworkRouting(IndustryProblem):
    key = "telecom.network_routing"
    industry = "telecommunications"
    title = "Capacity-aware network routing (path selection)"
    description = ("Route each traffic demand on one of its candidate paths, minimising latency-weighted traffic and "
                   "congestion while respecting link capacities.")
    formulation = ("load_l = Σ_dp v_d x_dp [l ∈ p]\n"
                   "min  Σ_dp v_d (Σ_{l∈p} τ_l) x_dp + λ Σ_l load_l² / C_l\n"
                   "s.t. Σ_p x_dp = 1 ∀ demands ;  load_l ≤ C_l ∀ links (slack-encoded)")
    limitations = "Unsplittable flows over user-supplied candidate paths (no path enumeration, no multipath)."
    Input = RoutingInput

    def build_model(self, d: RoutingInput) -> Model:
        m = Model("network_routing")
        X = {(i, p): m.binary(f"r_{i}_{p}") for i, dm in enumerate(d.demands) for p in range(len(dm.paths))}
        loads = {k: [] for k in range(len(d.links))}
        lat = []
        for (i, p), x in X.items():
            dm = d.demands[i]
            pl = d.path_links(dm.paths[p])
            lat.append(dm.volume * sum(d.latency(k) for k in pl) * x)
            for k in pl:
                loads[k].append(dm.volume * x)
        load_e = {k: quicksum(v) for k, v in loads.items()}
        m.minimize(quicksum(lat) + d.congestion_weight * quicksum(e * e / d.link_capacity[k] for k, e in load_e.items()))
        for i, dm in enumerate(d.demands):
            m.add_one_hot([f"r_{i}_{p}" for p in range(len(dm.paths))], f"demand_{i}")
        for k, terms in loads.items():
            worst = sum(dm.volume for dm in d.demands if any(k in d.path_links(p) for p in dm.paths))
            if worst > d.link_capacity[k]:
                m.add_constraint(load_e[k] <= d.link_capacity[k], f"cap_{k}")
        return m

    def interpret(self, d: RoutingInput, a):
        load = [0] * len(d.links)
        routes, ok = {}, True
        for i, dm in enumerate(d.demands):
            ch = [p for p in range(len(dm.paths)) if a[f"r_{i}_{p}"]]
            ok &= len(ch) == 1
            routes[dm.name] = [[d.nodes[n] for n in dm.paths[p]] for p in ch]
            for p in ch:
                for k in d.path_links(dm.paths[p]):
                    load[k] += dm.volume
        util = {f"{d.nodes[u]}-{d.nodes[v]}": round(load[k] / d.link_capacity[k], 3) for k, (u, v) in enumerate(d.links)}
        return {"routes": routes, "link_utilisation": util, "one_path_each_ok": ok,
                "capacity_ok": all(load[k] <= d.link_capacity[k] for k in range(len(d.links))),
                "max_utilisation": max(util.values())}

    def example(self):
        return {"nodes": ["A", "B", "C", "D"], "links": [[0, 1], [1, 3], [0, 2], [2, 3], [1, 2]],
                "link_capacity": [3, 3, 3, 3, 2], "link_latency": [1, 1, 1.5, 1.5, 1],
                "demands": [{"name": "A→D video", "volume": 2, "paths": [[0, 1, 3], [0, 2, 3], [0, 1, 2, 3]]},
                            {"name": "B→D backhaul", "volume": 2, "paths": [[1, 3], [1, 2, 3]]},
                            {"name": "A→C voice", "volume": 1, "paths": [[0, 2], [0, 1, 2]]}],
                "congestion_weight": 0.5}
