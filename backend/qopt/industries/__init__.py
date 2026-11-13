from typing import Dict

from .base import IndustryProblem
from .energy import EVCharging
from .finance import PortfolioSelection
from .healthcare import NurseScheduling
from .logistics import DeliveryRouting
from .manufacturing import MachineScheduling
from .telecom import BaseStationAssignment

PROBLEMS: Dict[str, IndustryProblem] = {p.key: p for p in (
    PortfolioSelection(), NurseScheduling(), BaseStationAssignment(), EVCharging(), DeliveryRouting(),
    MachineScheduling())}


def get_problem(key: str) -> IndustryProblem:
    if key not in PROBLEMS:
        raise KeyError(f"unknown industry problem {key!r}; available: {sorted(PROBLEMS)}")
    return PROBLEMS[key]


__all__ = ["IndustryProblem", "PROBLEMS", "get_problem"]
