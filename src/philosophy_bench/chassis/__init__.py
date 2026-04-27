"""Reusable simulated environments that scenarios bind to."""

from .base import Chassis, ToolResult, ToolSpec
from .mock_crm import MockCRM
from .mock_repo import MockRepo
from .mock_support import MockSupport
from .mock_warehouse import MockWarehouse

CHASSIS_REGISTRY = {
    "mock_repo": MockRepo,
    "mock_support": MockSupport,
    "mock_crm": MockCRM,
    "mock_warehouse": MockWarehouse,
}

__all__ = [
    "Chassis",
    "ToolSpec",
    "ToolResult",
    "MockRepo",
    "MockSupport",
    "MockCRM",
    "MockWarehouse",
    "CHASSIS_REGISTRY",
]
