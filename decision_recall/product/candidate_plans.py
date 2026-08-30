"""Authored example plans for registered records; no Gemini execution/evidence.

Registration data only. These plans do not contain outcomes, authority, or policy.
The legacy credentialed release evidence and legacy compiler remain separate.
"""
from .compiler import CandidateKind
from .configured_candidates import ConfiguredCandidatePlan, ConfiguredCandidateSpec


def registered_candidate_plans() -> tuple[ConfiguredCandidatePlan, ...]:
    return (
        ConfiguredCandidatePlan("D-104", "SUPPLIER_RESILIENCE", "1", (
            ConfiguredCandidateSpec("apex_delivery_instability", CandidateKind.FACT,
                                    "decision-note", "Apex delivery performance has been materially unstable."),
            ConfiguredCandidateSpec("beacon_reactivation_delay", CandidateKind.FACT,
                                    "supplier-record", "Beacon requires roughly 10 weeks to reactivate."),
            ConfiguredCandidateSpec("historical_support:apex_delivery_instability", CandidateKind.HISTORICAL_ROLE,
                                    "decision-note", "Apex instability materially influenced the decision."),
        )),
        ConfiguredCandidatePlan("D-205", "RELEASE_ROLLBACK_REUSE", "1", (
            ConfiguredCandidateSpec("elevated_release_errors", CandidateKind.FACT,
                                    "incident-record", "Orion v42 had a 5% request error rate over one day."),
            ConfiguredCandidateSpec("recovery_rehearsal_passed", CandidateKind.FACT,
                                    "recovery-record", "Orion v41 passed every restore attempt in a one-day recovery rehearsal."),
            ConfiguredCandidateSpec("historical_support:elevated_release_errors", CandidateKind.HISTORICAL_ROLE,
                                    "incident-record", "The elevated Orion v42 errors materially influenced the rollback decision."),
        )),
    )
