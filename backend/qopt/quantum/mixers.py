"""QAOA mixers.

A mixer provides (1) its initial state, (2) a sequence of *components*, each a unitary
``exp(-i β A_k)`` with a cheap generator ``A_k`` (used by adjoint differentiation), and
(3) the equivalent Qiskit gates. Implement :class:`Mixer` to add custom mixers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Sequence, Tuple

import numpy as np

Component = Tuple[Callable[[np.ndarray, float], np.ndarray], Callable[[np.ndarray], np.ndarray]]


def _apply_rx_all(state: np.ndarray, beta: float, n: int) -> np.ndarray:
    """⊗_q RX(2β) = exp(-iβ Σ X_q)."""
    c, s = np.cos(beta), -1j * np.sin(beta)
    psi = state
    for q in range(n):
        v = psi.reshape(1 << (n - 1 - q), 2, 1 << q)
        a0 = v[:, 0, :].copy()
        a1 = v[:, 1, :]
        v[:, 0, :] = c * a0 + s * a1
        v[:, 1, :] = s * a0 + c * a1
    return psi


def _apply_sum_x(state: np.ndarray, n: int) -> np.ndarray:
    """(Σ_q X_q)|ψ⟩."""
    out = np.zeros_like(state)
    idx = np.arange(state.shape[0])
    for q in range(n):
        out += state[idx ^ (1 << q)]
    return out


class Mixer(ABC):
    name: str = "custom"

    @abstractmethod
    def initial_state(self, n: int) -> np.ndarray: ...

    @abstractmethod
    def components(self, n: int) -> List[Component]: ...

    @abstractmethod
    def qiskit_prepare(self, qc, n: int) -> None: ...

    @abstractmethod
    def qiskit_layer(self, qc, beta, n: int) -> None: ...

    def describe(self) -> dict:
        return {"name": self.name}

    def apply(self, state: np.ndarray, beta: float, n: int) -> np.ndarray:
        for u, _ in self.components(n):
            state = u(state, beta)
        return state


class XMixer(Mixer):
    """Standard transverse-field mixer H_M = Σ X_i, initial state |+⟩^n."""
    name = "x"

    def initial_state(self, n: int) -> np.ndarray:
        return np.full(1 << n, (1 << n) ** -0.5, dtype=complex)

    def components(self, n: int) -> List[Component]:
        return [(lambda s, b: _apply_rx_all(s, b, n), lambda s: _apply_sum_x(s, n))]

    def qiskit_prepare(self, qc, n: int) -> None:
        qc.h(range(n))

    def qiskit_layer(self, qc, beta, n: int) -> None:
        for q in range(n):
            qc.rx(2 * beta, q)


class XYRingMixer(Mixer):
    """Hamming-weight-preserving ring XY mixer on disjoint one-hot groups (Hadfield et al.).

    Each group g gets the sequence of gates exp(-iβ (X_aX_b + Y_aY_b)/2) over ring edges,
    starting from the W state (uniform superposition of one-hot states) on that group. All
    remaining qubits use the standard X mixer from |+⟩. Feasible one-hot structure is
    therefore preserved exactly by every layer."""
    name = "xy_ring"

    def __init__(self, groups: Sequence[Sequence[int]]):
        flat = [q for g in groups for q in g]
        if len(flat) != len(set(flat)):
            raise ValueError("XY mixer groups must be disjoint")
        if any(len(g) < 2 for g in groups):
            raise ValueError("each XY group needs at least 2 qubits")
        self.groups = [list(g) for g in groups]

    def describe(self) -> dict:
        return {"name": self.name, "groups": self.groups}

    def _edges(self) -> List[Tuple[int, int]]:
        edges = []
        for g in self.groups:
            k = len(g)
            ring = [(g[i], g[(i + 1) % k]) for i in range(k if k > 2 else 1)]
            edges += ring
        return edges

    def _free(self, n: int) -> List[int]:
        used = {q for g in self.groups for q in g}
        return [q for q in range(n) if q not in used]

    def initial_state(self, n: int) -> np.ndarray:
        # product of W states on groups ⊗ |+⟩ on free qubits
        amp = np.zeros(1 << n, dtype=complex)
        free = self._free(n)
        idx = np.arange(1 << n)
        mask = np.ones(1 << n, dtype=bool)
        norm = 1.0
        for g in self.groups:
            bits = sum(((idx >> q) & 1) for q in g)
            mask &= bits == 1
            norm *= len(g)
        norm *= 2 ** len(free)
        amp[mask] = norm ** -0.5
        return amp

    def components(self, n: int) -> List[Component]:
        comps: List[Component] = []
        idx = np.arange(1 << n)
        for a, b in self._edges():
            sel = idx[(((idx >> a) & 1) == 1) & (((idx >> b) & 1) == 0)]   # |..1_a..0_b..⟩
            partner = sel ^ (1 << a) ^ (1 << b)                               # |..0_a..1_b..⟩

            def u(s, beta, sel=sel, partner=partner):
                c, si = np.cos(beta), -1j * np.sin(beta)
                p, q = s[sel].copy(), s[partner].copy()
                s[sel] = c * p + si * q
                s[partner] = si * p + c * q
                return s

            def gen(s, sel=sel, partner=partner):
                out = np.zeros_like(s)
                out[sel] = s[partner]
                out[partner] = s[sel]
                return out

            comps.append((u, gen))
        free = self._free(n)
        if free:
            def uf(s, beta):
                c, si = np.cos(beta), -1j * np.sin(beta)
                for q in free:
                    v = s.reshape(1 << (n - 1 - q), 2, 1 << q)
                    a0 = v[:, 0, :].copy(); a1 = v[:, 1, :]
                    v[:, 0, :] = c * a0 + si * a1
                    v[:, 1, :] = si * a0 + c * a1
                return s

            def gf(s):
                out = np.zeros_like(s)
                for q in free:
                    out += s[idx ^ (1 << q)]
                return out
            comps.append((uf, gf))
        return comps

    def qiskit_prepare(self, qc, n: int) -> None:
        from qiskit.circuit.library import StatePreparation
        for g in self.groups:
            k = len(g)
            w = np.zeros(1 << k)
            for j in range(k):
                w[1 << j] = k ** -0.5
            qc.append(StatePreparation(w), [g[j] for j in range(k)])
        for q in self._free(n):
            qc.h(q)

    def qiskit_layer(self, qc, beta, n: int) -> None:
        from qiskit.circuit.library import XXPlusYYGate
        # XXPlusYYGate(θ) = exp(-i θ/2 · (XX+YY)/2)  ⇒  θ = 2β
        for a, b in self._edges():
            qc.append(XXPlusYYGate(2 * beta), [a, b])
        for q in self._free(n):
            qc.rx(2 * beta, q)


def make_mixer(name: str, groups: Sequence[Sequence[int]] | None = None) -> Mixer:
    if name == "x":
        return XMixer()
    if name in ("xy", "xy_ring"):
        if not groups:
            raise ValueError("the XY mixer requires one-hot constraint groups "
                             "(model constraints declared with kind='one_hot')")
        return XYRingMixer(groups)
    raise ValueError(f"unknown mixer {name!r} (supported: 'x', 'xy_ring', or a custom Mixer)")
