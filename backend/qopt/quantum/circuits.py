"""Qiskit QAOA circuit construction, gate-list export (for the UI) and OpenQASM export.

The circuit implements exactly the same unitary as :class:`StatevectorQAOA` (up to global
phase) — enforced by tests comparing Qiskit's Statevector with the NumPy simulator.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from ..core.qubo import QUBO
from .mixers import Mixer, XMixer


def build_qaoa_circuit(qubo: QUBO, p: int, mixer: Optional[Mixer] = None, measure: bool = False,
                       scale: Optional[float] = None):
    """Parameterised circuit with ParameterVectors γ (len p) and β (len p).

    Cost layer exp(-iγ H_C/scale), H_C = Σ h_i Z_i + Σ J_ij Z_i Z_j  →  RZ(2γh_i/s), RZZ(2γJ_ij/s).
    """
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector

    mixer = mixer or XMixer()
    n = qubo.num_variables
    ising = qubo.to_ising()
    if scale is None:
        coeffs = [abs(v) for v in ising.h.values()] + [abs(v) for v in ising.J.values()]
        scale = max(coeffs) if coeffs else 1.0
    gam = ParameterVector("γ", p)
    bet = ParameterVector("β", p)
    qc = QuantumCircuit(n, name=f"QAOA(p={p})")
    mixer.qiskit_prepare(qc, n)
    for l in range(p):
        qc.barrier()
        for i, h in sorted(ising.h.items()):
            qc.rz(2 * gam[l] * h / scale, i)
        for (i, j), J in sorted(ising.J.items()):
            qc.rzz(2 * gam[l] * J / scale, i, j)
        qc.barrier()
        mixer.qiskit_layer(qc, bet[l], n)
    if measure:
        qc.measure_all()
    return qc, list(gam), list(bet), scale


def bind(qc, gammas_params, betas_params, gammas: Sequence[float], betas: Sequence[float]):
    mapping = {g: float(v) for g, v in zip(gammas_params, gammas)}
    mapping.update({b: float(v) for b, v in zip(betas_params, betas)})
    return qc.assign_parameters(mapping)


def circuit_summary(qc) -> dict:
    ops = {k: int(v) for k, v in qc.count_ops().items()}
    return {"num_qubits": qc.num_qubits, "depth": qc.depth(), "size": qc.size(), "ops": ops,
            "two_qubit_gates": sum(v for k, v in ops.items() if k in ("rzz", "cx", "cz", "xx_plus_yy", "ecr"))}


def gate_list(qc, max_gates: int = 5000) -> List[dict]:
    """Serialisable gate list for the frontend circuit renderer."""
    out = []
    for inst in qc.data[:max_gates]:
        op = inst.operation
        qubits = [qc.find_bit(q).index for q in inst.qubits]
        params = []
        for prm in op.params:
            try:
                params.append(float(prm))
            except (TypeError, ValueError):
                params.append(str(prm))
        out.append({"gate": op.name, "qubits": qubits, "params": params})
    return out


def to_qasm3(qc) -> str:
    from qiskit import qasm3
    return qasm3.dumps(qc)


def draw_text(qc, fold: int = 120) -> str:
    return str(qc.draw(output="text", fold=fold))
