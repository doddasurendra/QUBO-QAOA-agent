from typing import Dict

from .base import IndustryProblem
from .energy import EVCharging
from .energy_ext import BatteryScheduling, UnitCommitment
from .energy_flex import DemandResponse, RenewableAllocation
from .finance import PortfolioSelection
from .finance_ext import FraudFeatureSelection, InvestmentAllocation, TransactionScheduling
from .healthcare import NurseScheduling
from .healthcare_ext import ClinicalTrialSites, CompoundSelection, OperatingRoomScheduling
from .logistics import DeliveryRouting
from .logistics_ext import CargoLoading, DockScheduling, VehicleRouting
from .manufacturing import MachineScheduling
from .manufacturing_ext import JobShopScheduling
from .supply_chain import FacilityLocation, ProductionPlanning, SupplierSelection
from .supply_chain_echelon import EchelonNetworkDesign, MultiEchelonReplenishment
from .telecom import BaseStationAssignment
from .telecom_ext import NetworkRouting, SpectrumAllocation

PROBLEMS: Dict[str, IndustryProblem] = {p.key: p for p in (
    # finance
    PortfolioSelection(), InvestmentAllocation(), FraudFeatureSelection(), TransactionScheduling(),
    # healthcare
    NurseScheduling(), OperatingRoomScheduling(), ClinicalTrialSites(), CompoundSelection(),
    # telecommunications
    BaseStationAssignment(), SpectrumAllocation(), NetworkRouting(),
    # energy
    EVCharging(), UnitCommitment(), BatteryScheduling(), RenewableAllocation(), DemandResponse(),
    # logistics
    DeliveryRouting(), VehicleRouting(), CargoLoading(), DockScheduling(),
    # manufacturing
    MachineScheduling(), JobShopScheduling(), ProductionPlanning(),
    # supply chain
    FacilityLocation(), SupplierSelection(), EchelonNetworkDesign(), MultiEchelonReplenishment(),
)}


def get_problem(key: str) -> IndustryProblem:
    if key not in PROBLEMS:
        raise KeyError(f"unknown industry problem {key!r}; available: {sorted(PROBLEMS)}")
    return PROBLEMS[key]


__all__ = ["IndustryProblem", "PROBLEMS", "get_problem"]
