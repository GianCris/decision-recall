"""Bounded registered-case service/read models; no HTTP or case-specific rules.

Every request reconstructs state from server registration. Binding hashes are
consistency checks, not identity credentials or durable capture receipts. Supplied
numeric observations are example input, not authenticated external-system facts.
"""
from datetime import datetime, timezone
import json
from math import isfinite
from types import MappingProxyType

from ..domain import HistoricalKnowledgeState, NumericObservation, ProvenanceType
from ..m21 import canonical_hash
from ..temporal import RawWorldEvidence, TemporalReference, source_hash
from .capture import ProfileBinder
from .configured_candidates import ConfiguredCandidateCompiler
from .declaration import CaptureAnswer, capture_question_hash
from .lifecycle import prepare_decision, complete_decision_capture, reevaluate_decision


CANDIDATE_SOURCE_MODE = "configured_mechanically_grounded_example_candidates"
OBSERVATION_SOURCE_MODE = "supplied_current_example_record"
_BINDING_KEYS = frozenset({"decision_id", "capture_session_id", "profile_hash", "gap_id", "question_hash"})
_CAPTURE_KEYS = _BINDING_KEYS | {"answer"}
_OBSERVATION_KEYS = frozenset({"metric_key", "value", "unit", "window_days", "observed_at"})


class UnknownCase(ValueError):
    pass


class CaseBindingMismatch(ValueError):
    pass


def _exact_object(value, keys, name):
    if type(value) is not dict or value.keys() != keys:
        raise ValueError(f"{name} must contain exactly: {', '.join(sorted(keys))}")
    return value


def _timestamp(value):
    if type(value) is not str or len(value) > 64:
        raise ValueError("timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("timestamp must be a valid timezone-aware ISO-8601 value") from exc


def _metric_schema(definition):
    """Only metrics required by the registered target; never expose thresholds."""
    contract, target = definition.contract_definition, definition.target
    match_ids = {b.current_match_rule_id for b in (*target.changed_bindings, *target.surviving_bindings)}
    rules = tuple(r for r in contract.current_match_rules if r.id in match_ids) + tuple(
        r for r in contract.revisit_rules if r.id in target.revisit_rule_ids
    )
    windows = {}
    for rule in rules:
        key, minimum = rule.condition.metric_key, rule.condition.minimum_window_days
        windows[key] = max(windows.get(key) or 0, minimum or 0) or None
    return tuple({
        "metric_key": spec.key, "unit": spec.unit, "minimum": spec.minimum,
        "maximum": spec.maximum, "minimum_window_days": windows[spec.key],
    } for spec in definition.metric_specs if spec.key in windows)


def _binding(preparation):
    gap = preparation.critical_gaps[0]
    return {
        "decision_id": preparation.draft_contract.id,
        "capture_session_id": preparation.assignment.session_id,
        "profile_hash": preparation.assignment.profile_hash,
        "gap_id": gap.slot_id,
        "question_hash": capture_question_hash(gap.question),
    }


def _relations(contract, established_ids):
    return [{
        "relation_id": relation.id, "subject_id": relation.subject_id,
        "knowledge_state": (HistoricalKnowledgeState.ESTABLISHED.value
                            if relation.id in established_ids else relation.knowledge_state.value),
    } for relation in contract.historical_relations]


def _historical_state(completion):
    contract = completion.materialized_contract
    return {
        "historical_relations": _relations(contract, set()),
        "compositions": [{"composition_id": item.id, "value": item.value.value}
                         for item in contract.composition_states],
    }


class RegisteredCaseAPI:
    """Registry/plans are server-owned; all mutable lifecycle objects are local."""

    def __init__(self, *, decisions, candidate_plans, example_observations=None):
        plans = {}
        for plan in candidate_plans:
            if plan.decision_id in plans:
                raise ValueError("duplicate API case registration")
            definition, instance, _ = decisions.resolve(plan.decision_id)
            if (plan.profile_id, plan.profile_version) != (definition.id, definition.version):
                raise ValueError("candidate plan must match registered profile/version")
            compiler = ConfiguredCandidateCompiler(plan=plan, contract=definition.contract(instance))
            profile, _ = ProfileBinder().bind(template=definition.capture_template, structure=definition.structure(instance))
            # Fail at server configuration, not midway through a capture request.
            compiler.compile_observable(observable=definition.observable(instance), profile=profile)
            plans[plan.decision_id] = plan
        self._decisions = decisions
        self._plans = MappingProxyType(plans)
        examples = {}
        for decision_id, example in (example_observations or {}).items():
            self._resolve(decision_id)
            _exact_object(example, {"world_time", "observations"}, "example observations")
            world_time = _timestamp(example["world_time"])
            observations = self._observations(decision_id, example["observations"], world_time)
            examples[decision_id] = json.dumps({"world_time": world_time.isoformat(), "observations": observations})
        self._examples = MappingProxyType(examples)

    def _resolve(self, decision_id):
        if decision_id not in self._plans:
            raise UnknownCase("unknown registered case")
        return self._decisions.resolve(decision_id)

    def _prepare(self, decision_id):
        definition, instance, _ = self._resolve(decision_id)
        compiler = ConfiguredCandidateCompiler(
            plan=self._plans[decision_id], contract=definition.contract(instance),
        )
        return prepare_decision(decisions=self._decisions, decision_id=decision_id, compiler=compiler)

    def cases(self):
        return {"cases": [self._metadata(case_id) for case_id in self._plans]}

    def _metadata(self, decision_id):
        definition, instance, _ = self._resolve(decision_id)
        return {
            "decision_id": instance.decision_id, "title": definition.contract_definition.action.replace("_", " "),
            "profile_id": definition.id, "profile_version": definition.version,
            "decision_time": instance.decision_time.isoformat(),
            "candidate_source_mode": CANDIDATE_SOURCE_MODE,
        }

    def preparation(self, decision_id):
        definition, instance, _ = self._resolve(decision_id)
        p = self._prepare(decision_id)
        return {
            **self._metadata(decision_id), **_binding(p), "status": "issued",
            "source_records": [{"source_id": item.source_id, "excerpt": item.content,
                                "observed_at": item.observed_at.isoformat()} for item in instance.source_records],
            "known_facts": [{"fact_id": item.id, "semantic_key": item.predicate_key}
                            for item in p.draft_contract.claims if item.id in p.known_fact_ids],
            "historical_relations": _relations(p.draft_contract, p.established_relation_ids),
            "unresolved_relation_id": p.critical_gaps[0].slot_id,
            "question": p.critical_gaps[0].question,
            "metric_schema": list(_metric_schema(definition)),
            "observation_source_mode": OBSERVATION_SOURCE_MODE,
            "example_observations": json.loads(self._examples[decision_id]) if decision_id in self._examples else None,
            "current_match_labels": {
                rule.id: next(claim.predicate_key.replace("_", " ") for claim in p.draft_contract.claims if claim.id == rule.premise_id)
                for rule in p.draft_contract.current_match_rules
            },
        }

    def _verified_completion(self, decision_id, payload):
        self._resolve(decision_id)
        request = _exact_object(payload, _CAPTURE_KEYS, "capture")
        if any(type(value) is not str or not value.strip() or len(value) > 256 for value in request.values()):
            raise ValueError("capture values must be bounded non-empty strings")
        if request["answer"] != CaptureAnswer.YES.value:
            raise ValueError("registered-case capture accepts only answer=yes")
        p = self._prepare(decision_id)
        if any(request[key] != expected for key, expected in _binding(p).items()):
            raise CaseBindingMismatch("capture does not match the server-issued decision/session/profile/gap/question")
        return complete_decision_capture(p, decisions=self._decisions, capture_answer=CaptureAnswer.YES)

    def capture(self, decision_id, payload):
        c = self._verified_completion(decision_id, payload)
        return {
            **self._metadata(decision_id), **_historical_state(c),
            "status": "capture_verified", "capture_binding": _binding(c.preparation),
            "future_evaluation_status": "not_run",
        }

    def _observations(self, decision_id, observations, world_time):
        definition, instance, _ = self._resolve(decision_id)
        schema = {item["metric_key"]: item for item in _metric_schema(definition)}
        if world_time <= instance.decision_time:
            raise ValueError("world_time must be later than decision time")
        if type(observations) is not list or len(observations) != len(schema):
            raise ValueError("observations must cover exactly the required metrics")
        normalized = {}
        for item in observations:
            item = _exact_object(item, _OBSERVATION_KEYS, "observation")
            key = item["metric_key"]
            if type(key) is not str or key not in schema or key in normalized:
                raise ValueError("unknown or duplicate required metric")
            spec = schema[key]
            value = item["value"]
            if type(value) not in (int, float):
                raise ValueError("observation value must be finite numeric data, not boolean")
            try:
                value = float(value)
            except OverflowError as exc:
                raise ValueError("observation value must be finite") from exc
            if (not isfinite(value) or (spec["minimum"] is not None and value < spec["minimum"])
                    or (spec["maximum"] is not None and value > spec["maximum"])):
                raise ValueError("observation value is non-finite or outside registered range")
            if item["unit"] != spec["unit"]:
                raise ValueError("observation unit differs from registered schema")
            window = item["window_days"]
            if window is not None and (type(window) is not int or window <= 0):
                raise ValueError("window_days must be a positive integer or null")
            if spec["minimum_window_days"] is not None and (window is None or window < spec["minimum_window_days"]):
                raise ValueError("observation window is shorter than required by registered rules")
            observed = _timestamp(item["observed_at"])
            if not instance.decision_time < observed <= world_time:
                raise ValueError("observation must be after decision time and no later than world_time")
            normalized[key] = {
                "metric_key": key, "value": value, "unit": spec["unit"],
                "window_days": window, "observed_at": observed.isoformat(),
            }
        if normalized.keys() != schema.keys():
            raise ValueError("missing required metric")
        return tuple(normalized[key] for key in sorted(normalized))

    def reevaluate(self, decision_id, payload):
        self._resolve(decision_id)
        request = _exact_object(payload, {"capture", "world_time", "observations"}, "reevaluation")
        world_time = _timestamp(request["world_time"])
        observations = self._observations(decision_id, request["observations"], world_time)
        c = self._verified_completion(decision_id, request["capture"])
        evidence = []
        for observation in observations:
            envelope = {"decision_id": decision_id, "source": OBSERVATION_SOURCE_MODE, **observation}
            content = json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False)
            evidence.append(RawWorldEvidence(
                id=f"WE-SUPPLIED-{canonical_hash(envelope)}", content=content,
                source_id=OBSERVATION_SOURCE_MODE, source_span="complete server-rendered supplied observation",
                source_content_hash=source_hash(content), provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
                temporal_reference=TemporalReference.point(_timestamp(observation["observed_at"])),
                observations=(NumericObservation(observation["metric_key"], observation["value"],
                                                 observation["unit"], observation["window_days"]),),
            ))
        result = reevaluate_decision(c, decisions=self._decisions, later_world_evidence=tuple(evidence), world_time=world_time)
        canonical = result.evaluation.canonical_result
        return {
            **self._metadata(decision_id), **_historical_state(c), "status": "reevaluated",
            "world_time": world_time.isoformat(), "observation_source_mode": OBSERVATION_SOURCE_MODE,
            "admitted_observations": [{**item, "evidence_id": record.id} for item, record in zip(observations, evidence)],
            "current_matches": dict(canonical.current_matches),
            "safe_reuse_result": canonical.safe_reuse_result,
            "limiting_requirements": list(canonical.limiting_requirements),
            "reason_codes": list(canonical.reason_codes),
            "evaluation_hash": result.evaluation.result_hash,
            "replay_hash": result.replayed_result.result_hash(),
        }


def registered_case_api():
    from .candidate_plans import registered_candidate_plans
    from .registered_decisions import registered_decisions
    from .example_observations import registered_example_observations

    return RegisteredCaseAPI(decisions=registered_decisions(), candidate_plans=registered_candidate_plans(),
                             example_observations=registered_example_observations())
