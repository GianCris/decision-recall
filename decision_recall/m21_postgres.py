from __future__ import annotations

import json
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from .domain import TargetRef
from .m21 import (
    AuthorizationScope,
    CanonicalArtifact,
    CanonicalEvaluationResult,
    M21Registry,
    ScopedAuthorization,
    StrongDecisionCommit,
    StrongEvaluationSnapshot,
)
from .temporal import AuthorizedAssertion, TemporalIntegrityError


metadata_m21 = MetaData()

artifacts = Table(
    "dr_m21_artifacts",
    metadata_m21,
    Column("artifact_id", String(300), primary_key=True),
    Column("kind", String(80), nullable=False),
    Column("semantic_id", String(200), nullable=False),
    Column("semantic_version", String(120), nullable=False),
    Column("canonicalization_version", String(80), nullable=False),
    Column("canonical_json", Text, nullable=False),
    Column("content_hash", String(128), nullable=False),
)

scoped_authorizations = Table(
    "dr_m21_scoped_authorizations",
    metadata_m21,
    Column("authorization_id", String(200), primary_key=True),
    Column("contract_artifact_id", String(300), nullable=False),
    Column("entity_id", String(200), nullable=False),
    Column("entity_definition_hash", String(128), nullable=False),
    Column("authorized_assertion", String(120), nullable=False),
    Column("evidence_id", String(200), nullable=False),
    Column("policy_version", String(120), nullable=False),
    Column("policy_hash", String(128), nullable=False),
    Column("scope", String(80), nullable=False),
    Column("scope_ref", String(200), nullable=False),
    Column("target_id", String(200)),
    Column("target_version", String(120)),
)

strong_commits = Table(
    "dr_m21_strong_commits",
    metadata_m21,
    Column("commit_id", String(200), primary_key=True),
    Column("decision_id", String(200), nullable=False),
    Column("contract_artifact_id", String(300), nullable=False),
    Column("contract_hash", String(128), nullable=False),
    Column("contract_version", String(120), nullable=False),
    Column("capture_profile_version", String(200), nullable=False),
    Column("capture_profile_hash", String(128), nullable=False),
    Column("commit_cutoff_seq", BigInteger, nullable=False),
    UniqueConstraint("decision_id", "contract_version", name="uq_dr_m21_decision_version"),
)

strong_evaluations = Table(
    "dr_m21_strong_evaluations",
    metadata_m21,
    Column("evaluation_id", String(200), primary_key=True),
    Column("decision_commit_id", String(200), nullable=False),
    Column("contract_hash", String(128), nullable=False),
    Column("input_cutoff_seq", BigInteger, nullable=False),
    Column("world_time", DateTime(timezone=True), nullable=False),
    Column("target_artifact_id", String(300), nullable=False),
    Column("target_hash", String(128), nullable=False),
    Column("world_schema_artifact_id", String(300), nullable=False),
    Column("world_schema_hash", String(128), nullable=False),
    Column("authority_policy_version", String(120), nullable=False),
    Column("authority_policy_hash", String(128), nullable=False),
    Column("event_policy_version", String(120), nullable=False),
    Column("event_policy_hash", String(128), nullable=False),
    Column("engine_version", String(120), nullable=False),
    Column("engine_hash", String(128), nullable=False),
    Column("canonical_result_json", Text, nullable=False),
    Column("result_hash", String(128), nullable=False),
    Column("canonicalization_version", String(80), nullable=False),
)


class PostgresM21Store:
    """Durable registry for M2.1 semantic artifacts and replay snapshots."""

    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url, future=True)

    def create_schema(self) -> None:
        metadata_m21.create_all(self.engine)

    def drop_schema(self) -> None:
        metadata_m21.drop_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    def persist_registry(self, registry: M21Registry) -> None:
        with self.engine.begin() as conn:
            if registry.artifacts:
                conn.execute(
                    insert(artifacts),
                    [
                        {
                            "artifact_id": item.artifact_id,
                            "kind": item.kind,
                            "semantic_id": item.semantic_id,
                            "semantic_version": item.semantic_version,
                            "canonicalization_version": item.canonicalization_version,
                            "canonical_json": item.canonical_json,
                            "content_hash": item.content_hash,
                        }
                        for item in registry.artifacts.values()
                    ],
                )
            if registry.authorizations:
                conn.execute(
                    insert(scoped_authorizations),
                    [
                        {
                            "authorization_id": item.authorization_id,
                            "contract_artifact_id": item.contract_artifact_id,
                            "entity_id": item.entity_id,
                            "entity_definition_hash": item.entity_definition_hash,
                            "authorized_assertion": item.authorized_assertion.value,
                            "evidence_id": item.evidence_id,
                            "policy_version": item.policy_version,
                            "policy_hash": item.policy_hash,
                            "scope": item.scope.value,
                            "scope_ref": item.scope_ref,
                            "target_id": item.target_ref.id if item.target_ref else None,
                            "target_version": item.target_ref.version if item.target_ref else None,
                        }
                        for item in registry.authorizations.values()
                    ],
                )
            if registry.commits:
                conn.execute(
                    insert(strong_commits),
                    [item.__dict__ for item in registry.commits.values()],
                )
            if registry.evaluations:
                conn.execute(
                    insert(strong_evaluations),
                    [
                        {
                            "evaluation_id": item.evaluation_id,
                            "decision_commit_id": item.decision_commit_id,
                            "contract_hash": item.contract_hash,
                            "input_cutoff_seq": item.input_cutoff_seq,
                            "world_time": item.world_time,
                            "target_artifact_id": item.target_artifact_id,
                            "target_hash": item.target_hash,
                            "world_schema_artifact_id": item.world_schema_artifact_id,
                            "world_schema_hash": item.world_schema_hash,
                            "authority_policy_version": item.authority_policy_version,
                            "authority_policy_hash": item.authority_policy_hash,
                            "event_policy_version": item.event_policy_version,
                            "event_policy_hash": item.event_policy_hash,
                            "engine_version": item.engine_version,
                            "engine_hash": item.engine_hash,
                            "canonical_result_json": item.canonical_result.canonical_json(),
                            "result_hash": item.result_hash,
                            "canonicalization_version": item.canonicalization_version,
                        }
                        for item in registry.evaluations.values()
                    ],
                )

    def load_registry(self) -> M21Registry:
        registry = M21Registry()
        with self.engine.connect() as conn:
            for row in conn.execute(select(artifacts).order_by(artifacts.c.artifact_id)).all():
                registry.add_artifact(
                    CanonicalArtifact(
                        artifact_id=row.artifact_id,
                        kind=row.kind,
                        semantic_id=row.semantic_id,
                        semantic_version=row.semantic_version,
                        canonicalization_version=row.canonicalization_version,
                        canonical_json=row.canonical_json,
                        content_hash=row.content_hash,
                    )
                )
            for row in conn.execute(
                select(scoped_authorizations).order_by(scoped_authorizations.c.authorization_id)
            ).all():
                target_ref = None
                if row.target_id is not None:
                    if row.target_version is None:
                        raise TemporalIntegrityError("persisted scoped authorization target is incomplete")
                    target_ref = TargetRef(row.target_id, row.target_version)
                registry.add_authorization(
                    ScopedAuthorization(
                        authorization_id=row.authorization_id,
                        contract_artifact_id=row.contract_artifact_id,
                        entity_id=row.entity_id,
                        entity_definition_hash=row.entity_definition_hash,
                        authorized_assertion=AuthorizedAssertion(row.authorized_assertion),
                        evidence_id=row.evidence_id,
                        policy_version=row.policy_version,
                        policy_hash=row.policy_hash,
                        scope=AuthorizationScope(row.scope),
                        scope_ref=row.scope_ref,
                        target_ref=target_ref,
                    )
                )
            for row in conn.execute(select(strong_commits).order_by(strong_commits.c.commit_id)).all():
                registry.add_commit(StrongDecisionCommit(**dict(row._mapping)))
            for row in conn.execute(
                select(strong_evaluations).order_by(strong_evaluations.c.evaluation_id)
            ).all():
                envelope = json.loads(row.canonical_result_json)
                value = envelope["value"]
                result = CanonicalEvaluationResult(
                    safe_reuse_result=value["safe_reuse_result"],
                    limiting_requirements=tuple(value["limiting_requirements"]),
                    reason_codes=tuple(value["reason_codes"]),
                    current_matches=tuple(tuple(item) for item in value["current_matches"]),
                    review_states=tuple(tuple(item) for item in value["review_states"]),
                    canonicalization_version=value["canonicalization_version"],
                )
                evaluation = StrongEvaluationSnapshot(
                    evaluation_id=row.evaluation_id,
                    decision_commit_id=row.decision_commit_id,
                    contract_hash=row.contract_hash,
                    input_cutoff_seq=int(row.input_cutoff_seq),
                    world_time=row.world_time,
                    target_artifact_id=row.target_artifact_id,
                    target_hash=row.target_hash,
                    world_schema_artifact_id=row.world_schema_artifact_id,
                    world_schema_hash=row.world_schema_hash,
                    authority_policy_version=row.authority_policy_version,
                    authority_policy_hash=row.authority_policy_hash,
                    event_policy_version=row.event_policy_version,
                    event_policy_hash=row.event_policy_hash,
                    engine_version=row.engine_version,
                    engine_hash=row.engine_hash,
                    canonical_result=result,
                    result_hash=row.result_hash,
                    canonicalization_version=row.canonicalization_version,
                )
                registry.add_evaluation(evaluation)
        return registry
