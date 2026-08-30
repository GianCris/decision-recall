"""Product-facing Decision Recall orchestration.

The product layer is intentionally thin: it composes capture, temporal authority,
strict replay, and DTO projection without owning epistemic semantics.
"""

from .golden_loop import run_golden_decision

__all__ = ["run_golden_decision"]
