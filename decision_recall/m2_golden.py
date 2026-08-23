"""Milestone 2 golden seeds.

M1 intentionally keeps its historical fixture stable. M2 uses this module so the
canonical temporal story starts from the stricter epistemic state:

    C1 = NOT_DURABLY_RECORDED

unless contemporaneous evidence explicitly authorized T0_UNRESOLVED.
"""

from .domain import CompositionValue, DecisionContract
from .golden import supplier_resilience_contract


def supplier_resilience_temporal_contract() -> DecisionContract:
    return supplier_resilience_contract(
        c1_value=CompositionValue.NOT_DURABLY_RECORDED,
    )
