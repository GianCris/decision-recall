"""Mechanism-neutral baseline scaffold for DR-Bench v0.1."""

from .baselines import B0, B1, B2, BASE_TASK_PROMPT, REEVALUATION_INSTRUCTION, get_baseline
from .config import ExperimentConfig, RetryPolicy
from .models import DeterministicMockAdapter, ModelAdapter, ModelResponse
from .output import (
    DISCOVERY_RESPONSE_JSON_SCHEMA,
    DISCOVERY_RESPONSE_MIME_TYPE,
    DISCOVERY_RESPONSE_SCHEMA_VERSION,
)
from .google_adapter import GeminiAuthenticationError, GeminiVertexAdapter
from .output import OutputValidationError, parse_discovery_response
from .records import RunRecord
from .runner import run_baseline

__all__ = [
    "B0", "B1", "B2", "BASE_TASK_PROMPT", "REEVALUATION_INSTRUCTION",
    "DeterministicMockAdapter", "ExperimentConfig", "GeminiAuthenticationError",
    "GeminiVertexAdapter", "ModelAdapter", "ModelResponse",
    "DISCOVERY_RESPONSE_JSON_SCHEMA",
    "DISCOVERY_RESPONSE_MIME_TYPE", "DISCOVERY_RESPONSE_SCHEMA_VERSION",
    "OutputValidationError", "RetryPolicy", "RunRecord", "get_baseline",
    "parse_discovery_response", "run_baseline",
]

__version__ = "0.1.0"
