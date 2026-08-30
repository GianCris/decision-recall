"""Internal example registration only; no public routing or semantic dispatch."""
from .d104 import d104_registry
from .d205 import IDENTITY, d205_instance, d205_profile
from .definitions import DecisionRegistry


def registered_decisions() -> DecisionRegistry:
    profile, instance, identity = d104_registry().resolve("D-104")
    return DecisionRegistry(
        profiles=(profile, d205_profile()),
        instances=(instance, d205_instance()),
        identities=((instance.decision_id, identity), ("D-205", IDENTITY)),
    )
