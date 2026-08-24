from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import FrozenSet, Tuple

from ..domain import CompositionState, RelationCandidate, RelationSlot, RelationType
from ..m21 import CANONICALIZATION_V1, CanonicalArtifact, canonical_json


@dataclass(frozen=True)
class CaptureSlotTemplate:
    """Reusable structured policy. It contains no concrete decision/entity ids."""

    semantic_role: str
    relation_type: RelationType
    subject_predicate_key: str
    requires_subject_fact: bool
    ephemeral_if_unresolved: bool
    priority: int
    question_pattern: str


@dataclass(frozen=True)
class CaptureProfileTemplate:
    id: str
    version: str
    question_budget: int
    slots: Tuple[CaptureSlotTemplate, ...]


@dataclass(frozen=True)
class CaptureInstantiationContext:
    decision_id: str
    relation_id: str
    subject_id: str
    subject_predicate_key: str
    subject_display: str
    decision_display: str = "this decision"


@dataclass(frozen=True)
class CaptureSlotSpec:
    """Concrete t0 slot produced from a reusable template plus observable bindings."""

    semantic_role: str
    slot: RelationSlot
    requires_subject_fact: bool
    ephemeral_if_unresolved: bool
    priority: int
    question_text: str


@dataclass(frozen=True)
class CaptureProfile:
    id: str
    version: str
    template_id: str
    template_version: str
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


def supplier_resilience_capture_template() -> CaptureProfileTemplate:
    return CaptureProfileTemplate(
        id="SUPPLIER_RESILIENCE_CAPTURE",
        version="SUPPLIER_RESILIENCE_TEMPLATE_V1",
        question_budget=1,
        slots=(
            CaptureSlotTemplate(
                semantic_role="REACTION_CAPACITY_HISTORICAL_ROLE",
                relation_type=RelationType.HISTORICAL_SUPPORT,
                subject_predicate_key="beacon_reactivation_delay",
                requires_subject_fact=True,
                ephemeral_if_unresolved=True,
                priority=100,
                question_pattern="Did {subject_display} materially influence {decision_display}?",
            ),
        ),
    )


def instantiate_capture_profile(
    *,
    template: CaptureProfileTemplate,
    context: CaptureInstantiationContext,
) -> CaptureProfile:
    matches = tuple(
        item for item in template.slots
        if item.subject_predicate_key == context.subject_predicate_key
    )
    if len(matches) != 1:
        raise ValueError("capture template must match exactly one subject semantic role")
    item = matches[0]
    slot = RelationSlot(
        id=context.relation_id,
        relation_type=item.relation_type,
        subject_id=context.subject_id,
        object_id=context.decision_id,
        reason_for_checking=item.semantic_role,
    )
    question = item.question_pattern.format(
        subject_display=context.subject_display,
        decision_display=context.decision_display,
    )
    return CaptureProfile(
        id=f"{template.id}:{context.decision_id}",
        version="CAPTURE_PROFILE_INSTANCE_V1",
        template_id=template.id,
        template_version=template.version,
        question_budget=template.question_budget,
        slots=(
            CaptureSlotSpec(
                semantic_role=item.semantic_role,
                slot=slot,
                requires_subject_fact=item.requires_subject_fact,
                ephemeral_if_unresolved=item.ephemeral_if_unresolved,
                priority=item.priority,
                question_text=question,
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


def _verify_assigned_profile(profile: CaptureProfile, assignment: ProfileAssignment) -> None:
    actual = make_capture_profile_artifact(profile)
    if assignment.profile_version != profile.version:
        raise ValueError("assigned profile version differs from supplied profile")
    if assignment.artifact_id != actual.artifact_id or assignment.profile_hash != actual.content_hash:
        raise ValueError("gap selector profile does not match the assigned canonical artifact")


def select_critical_gaps(
    *,
    profile: CaptureProfile,
    assignment: ProfileAssignment,
    decision_id: str,
    known_fact_ids: FrozenSet[str],
    established_relation_ids: FrozenSet[str],
    selected_at: datetime,
) -> Tuple[CriticalGap, ...]:
    """Select gaps from t0-only structured inputs; there is no future-world input."""

    _verify_assigned_profile(profile, assignment)
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
    return tuple(
        CriticalGap(
            slot_id=item.slot.id,
            subject_id=item.slot.subject_id,
            object_id=item.slot.object_id,
            question=item.question_text,
            selected_at=selected_at,
        )
        for item in eligible[: profile.question_budget]
    )


def candidate_fills_gap(
    *,
    profile: CaptureProfile,
    gap: CriticalGap,
    candidate: RelationCandidate,
) -> bool:
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


def composition_question_eligible(
    *,
    composition: CompositionState,
    established_relation_ids: FrozenSet[str],
) -> bool:
    """A sufficiency question is well-formed only after all referenced roles exist."""

    return bool(composition.relation_ids) and set(composition.relation_ids).issubset(established_relation_ids)
