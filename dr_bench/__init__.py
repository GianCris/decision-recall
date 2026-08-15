"""Public API for DR-Bench v0.1."""

from .catalog import load_scenario, load_scenarios
from .evaluator import DiscoveryEvaluation, RecoveryEvaluation, evaluate, evaluate_discovery, evaluate_recovery
from .simulator import simulate, simulate_recovery
from .validation import ScenarioValidationError, validate_scenario
from .views import candidate_view

__all__ = [
    "DiscoveryEvaluation",
    "RecoveryEvaluation",
    "ScenarioValidationError",
    "evaluate",
    "evaluate_discovery",
    "evaluate_recovery",
    "load_scenario",
    "load_scenarios",
    "simulate",
    "simulate_recovery",
    "candidate_view",
    "validate_scenario",
]

__version__ = "0.1.0"
