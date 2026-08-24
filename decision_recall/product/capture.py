from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import FrozenSet, Tuple

from ..domain import RelationCandidate, RelationSlot, RelationType
from ..m21 import CANONICALIZATION_V1, CanonicalArtifact, canonical_json


@dataclass(frozen=True)
class CaptureSlotSpec:
    """Structured capture policy for one prospective historical-role slot.

    `reason_for_checking` and `question_text` are presentation metadata only.
    Selection logic must use the structured fields.
    """

    slot: RelationSlot
    requires_subject_fact: bool
    ephemeral_if_unresolved: bool
    priority: int
    question_text: str


@dataclass(frozen=True)
class CaptureProfile:
    id: str
    version: str
    question_budget: int
    slots: Tuple[CaptureSlotSpec, ...]


@dataclass(frozen=True)
class ProfileAssignment:
    session_id: str
    artifact_id: str
    profile_hash: str
    profile_version: str
    assigned_at: datetime


@dataclass(frozen=True)
class CriticalGap:
    slot_id: str
    subject_id: str
    object_id: str
    question: str
    selected_at: datetime


def supplier_resilience_capture_profile() -> CaptureProfile:
    return CaptureProfile(
        id="SUPPLIER_RESILIENCE",
        version="SUPPLIER_RESILIENCE_V1",
        question_budget=1,
        slots=(
            CaptureSlotSpec(
                slot=RelationSlot(
                    id="R2",
                    relation_type=RelationType.HISTORICAL_SUPPORT,
                    subject_id="F2",
                    object_id="D-104",
                    reason_for_checking=(
                        "Known supplier-reactivation fact has unresolved historical role."
                    ),
                ),
                requires_subject_fact=True,
                ephemeral_if_unresolved=True,
                priority=100,
                question_text=(
                    "Did Beacon's roughly 10-week reactivation delay materially "
                    "influence this decision?"
                ),
            ),
        ),
    )


def make_capture_profile_artifact(profile: CaptureProfile) -> CanonicalArtifact:
    if profile.question_budget < 0:
        raise ValueError("question_budget cannot be negative")
    if not profile.id.strip() or not profile.version.strip():
        raise ValueError("capture profile id/version are required")
    slot_ids = tuple(item.slot.id for item in profile.slots)
    if len(slot_ids) != len(set(slot_ids)):
        raise ValueError("capture profile slot ids must be unique")
    text = canonical_json(profile)
    digest = sha256(text.encode("utf-8")).hexdigest()
    return CanonicalArtifact(
        artifact_id=f"CAPTURE_PROFILE:{profile.id}:{profile.version}:{digest[:16]}",
        kind="capture_profile",
        semantic_id=profile.id,
        semantic_version=profile.version,
        canonicalization_version=CANONICALIZATION_V1,
        canonical_json=text,
        content_hash=digest,
    )


def assign_profile(
    *,
    session_id: str,
    artifact: CanonicalArtifact,
    assigned_at: datetime,
) -> ProfileAssignment:
    if artifact.kind != "capture_profile":
        raise ValueError("profile assignment requires capture_profile artifact")
    if assigned_at.tzinfo is None or assigned_at.utcoffset() is None:
        raise ValueError("assigned_at must be timezone-aware")
    return ProfileAssignment(
        session_id=session_id,
        artifact_id=artifact.artifact_id,
        profile_hash=artifact.content_hash,
        profile_version=artifact.semantic_version,
        assigned_at=assigned_at,
    )


def select_critical_gaps(
    *,
    profile: CaptureProfile,
    assignment: ProfileAssignment,
    decision_id: str,
    known_fact_ids: FrozenSet[str],
    established_relation_ids: FrozenSet[str],
    selected_at: datetime,
) -> Tuple[CriticalGap, ...]:
    """Select gaps from t0-only structured inputs.

    There is intentionally no world-event/current-world argument. A future event
    cannot enter this API.
    """

    if assignment.profile_version != profile.version:
        raise ValueError("assigned profile version differs from supplied profile")
    if profile.question_budget == 0:
        return ()
    if selected_at.tzinfo is None or selected_at.utcoffset() is None:
        raise ValueError("selected_at must be timezone-aware")
    if selected_at < assignment.assigned_at:
        raise ValueError("profile assignment must precede gap selection")

    eligible = []
    for item in profile.slots:
        slot = item.slot
        if slot.object_id != decision_id:
            continue
        if slot.relation_type is not RelationType.HISTORICAL_SUPPORT:
            continue
        if slot.id in established_relation_ids:
            continue
        if item.requires_subject_fact and slot.subject_id not in known_fact_ids:
            continue
        if not item.ephemeral_if_unresolved:
            continue
        eligible.append(item)

    eligible.sort(key=lambda item: (-item.priority, item.slot.id))
    selected = eligible[: profile.question_budget]
    return tuple(
        CriticalGap(
            slot_id=item.slot.id,
            subject_id=item.slot.subject_id,
            object_id=item.slot.object_id,
            question=item.question_text,
            selected_at=selected_at,
        )
        for item in selected
    )


def candidate_fills_gap(
    *,
    profile: CaptureProfile,
    gap: CriticalGap,
    candidate: RelationCandidate,
) -> bool:
    """Validate that a probabilistic candidate fills the pre-assigned slot.

    This is structural only. It does not authorize the historical role.
    """

    slot_spec = next((item for item in profile.slots if item.slot.id == gap.slot_id), None)
    if slot_spec is None:
        return False
    slot = slot_spec.slot
    return (
        candidate.relation_type is slot.relation_type
        and candidate.subject_id == slot.subject_id
        and candidate.object_id == slot.object_id
        and bool(candidate.evidence_refs)
    )
