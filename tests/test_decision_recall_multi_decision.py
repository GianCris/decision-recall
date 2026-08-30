"""Backend example proof. Candidate fixtures are NOT credentialed model output."""
import ast
from dataclasses import asdict, fields, replace
from datetime import timedelta
import inspect
import json
import sys
import unittest

from decision_recall.domain import CompositionValue, HistoricalKnowledgeState
from decision_recall.m21_strict import strict_full_replay, strict_verify_full_replay
from decision_recall.temporal import LedgerEntryKind, TemporalIntegrityError, source_hash
from decision_recall.product import definitions, golden_loop, lifecycle
from decision_recall.product.compiler import CandidateBundle, CandidateKind, GroundedCandidate, DeterministicGoldenCompiler
from decision_recall.product.d205 import T0, T1, d205_instance, d205_profile, d205_later_evidence
from decision_recall.product.declaration import CaptureAnswer, make_structured_capture_declaration, declaration_to_evidence
from decision_recall.product.definitions import DecisionRegistry, ProductIdentity
from decision_recall.product.registered_decisions import registered_decisions


D205_CANDIDATE_FIXTURE = (
    ("elevated_release_errors", CandidateKind.FACT, "incident-record", "Orion v42 had a 5% request error rate over one day."),
    ("recovery_rehearsal_passed", CandidateKind.FACT, "recovery-record", "Orion v41 passed every restore attempt in a one-day recovery rehearsal."),
    ("historical_support:elevated_release_errors", CandidateKind.HISTORICAL_ROLE, "incident-record", "The elevated Orion v42 errors materially influenced the rollback decision."),
)


class ExactSpanFixtureCompiler:
    """Test-only adapter over declared candidate data; no case/authority logic."""

    def __init__(self, records):
        self.records = records

    def compile_observable(self, *, observable, profile):
        candidates = []
        for index, (key, kind, source_id, quote) in enumerate(self.records):
            content = observable.source_map()[source_id].content
            if content.count(quote) != 1:
                raise ValueError("fixture quote must occur exactly once")
            start = content.index(quote)
            candidates.append(GroundedCandidate(f"FIXTURE-{index}", key, kind, source_id, start, start + len(quote)))
        return CandidateBundle(tuple(candidates))


def prepare(registry=None):
    return lifecycle.prepare_decision(
        decisions=registry or registered_decisions(), decision_id="D-205",
        compiler=ExactSpanFixtureCompiler(D205_CANDIDATE_FIXTURE),
    )


def execute(registry, decision_id, compiler, evidence, world_time):
    preparation = lifecycle.prepare_decision(decisions=registry, decision_id=decision_id, compiler=compiler)
    completion = lifecycle.complete_decision_capture(preparation, decisions=registry, capture_answer=CaptureAnswer.YES)
    result = lifecycle.reevaluate_decision(completion, decisions=registry, later_world_evidence=evidence, world_time=world_time)
    return preparation, completion, result


def d205_run():
    return execute(registered_decisions(), "D-205", ExactSpanFixtureCompiler(D205_CANDIDATE_FIXTURE), d205_later_evidence(), T1)


def replay(completion, evaluation):
    policy = completion.event_policy
    return strict_full_replay(
        registry=completion.registry, ledger=completion.ledger, evaluation=evaluation,
        authority_policy=completion.authority_policy,
        event_policies={(policy.version, policy.policy_hash): policy},
        engine_version=lifecycle.ENGINE_VERSION, engine_hash=lifecycle.ENGINE_HASH,
    )


class MultiDecisionTests(unittest.TestCase):
    def test_preparation_derives_the_second_question_without_prior_authority(self):
        p = prepare()
        self.assertEqual(p.known_fact_ids, frozenset(("F201", "F202")))
        self.assertEqual(p.established_relation_ids, frozenset(("R201",)))
        self.assertEqual(p.draft_contract.relation("R202").knowledge_state, HistoricalKnowledgeState.NOT_DURABLY_RECORDED)
        self.assertEqual(p.critical_gaps[0].slot_id, "R202")
        self.assertEqual(p.critical_gaps[0].question,
                         "Did the fact that Orion v41 passed every restore attempt in a one-day recovery rehearsal materially influence the decision to roll back Orion v42 to Orion v41?")
        self.assertEqual(p.critical_gaps[0].question, p.profile.slots[0].question_text)
        self.assertEqual(p.assignment.profile_hash, p.profile_artifact.content_hash)
        self.assertEqual(p.session.remaining_budget, 0)
        self.assertNotIn("R202", {item.entity_id for item in p.resolved_precommit_candidates})
        for record in p.precommit_evidence:
            self.assertIn(record.content, p.observable.source_map()[record.source_id].content)

    def test_t0_has_no_later_failure_or_evaluation_and_only_capture_establishes_role(self):
        registry = registered_decisions()
        p = prepare(registry)
        self.assertTrue(all(item.observed_at <= T0 for item in p.observable.sources))
        self.assertNotIn("schema change", json.dumps(asdict(p.observable), default=str))
        c = lifecycle.complete_decision_capture(p, decisions=registry, capture_answer=CaptureAnswer.YES)
        self.assertEqual(c.materialized_contract.relation("R202").knowledge_state, HistoricalKnowledgeState.ESTABLISHED)
        self.assertEqual(c.materialized_contract.composition("C201").value, CompositionValue.NOT_DURABLY_RECORDED)
        kinds = {entry.kind for entry in c.ledger.entries_as_of(c.ledger.head_seq)}
        self.assertTrue(kinds.isdisjoint({LedgerEntryKind.RAW_WORLD_EVIDENCE, LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, LedgerEntryKind.EVALUATION}))
        self.assertEqual(c.registry.evaluations, {})
        self.assertEqual(c.ledger.head_seq, c.commit.commit_cutoff_seq)
        for answer in (CaptureAnswer.NO, CaptureAnswer.SKIP, CaptureAnswer.NOT_SURE):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                lifecycle.complete_decision_capture(prepare(registry), decisions=registry, capture_answer=answer)

    def test_later_failed_restore_naturally_denies_reuse_and_preserves_history(self):
        _, c, result = d205_run()
        canonical = result.evaluation.canonical_result
        self.assertEqual(canonical.safe_reuse_result, "reuse_not_authorized")
        self.assertEqual(canonical.reason_codes, ("REQUIRED_SURVIVING_SUPPORT_DOES_NOT_MATCH",))
        self.assertEqual(canonical.limiting_requirements, ("R202",))
        self.assertEqual(dict(canonical.current_matches), {"M201": "matches", "M202": "does_not_match"})
        self.assertEqual(c.materialized_contract.relation("R202").knowledge_state, HistoricalKnowledgeState.ESTABLISHED)
        self.assertEqual(c.materialized_contract.composition("C201").value, CompositionValue.NOT_DURABLY_RECORDED)
        self.assertEqual(result.evaluation.result_hash, "30380ccab0bf8cd2c8fefd6c4a82ca5d321c2ca3d4ad2bc986bbdc7d642bea8d")
        self.assertEqual(result.replayed_result, canonical)
        policy = c.event_policy
        verified = strict_verify_full_replay(
            registry=c.registry, ledger=c.ledger, evaluation_id=result.evaluation.evaluation_id,
            authority_policy=c.authority_policy, event_policies={(policy.version, policy.policy_hash): policy},
            engine_version=lifecycle.ENGINE_VERSION, engine_hash=lifecycle.ENGINE_HASH,
        )
        self.assertEqual(verified.result_hash(), result.evaluation.result_hash)

    def test_replay_respects_both_authorized_cutoff_and_effective_world_time(self):
        _, c, result = d205_run()
        for evaluation in (
            replace(result.evaluation, input_cutoff_seq=c.commit.commit_cutoff_seq),
            replace(result.evaluation, world_time=T0),
        ):
            with self.subTest(cutoff=evaluation.input_cutoff_seq, time=evaluation.world_time):
                before = replay(c, evaluation)
                self.assertEqual(before.reason_codes, ("TARGET_CURRENT_MATCH_UNKNOWN",))
                self.assertEqual(set(dict(before.current_matches).values()), {"unknown"})

    def test_world_schema_rejects_cross_case_evidence_before_ledger_mutation(self):
        registry = registered_decisions()
        cases = (
            (prepare(registry), golden_loop.default_golden_later_world_evidence(), golden_loop.T1),
            (golden_loop.prepare_golden_capture(), d205_later_evidence(), T1),
        )
        for p, evidence, world_time in cases:
            c = lifecycle.complete_decision_capture(p, decisions=registry, capture_answer=CaptureAnswer.YES)
            before = (c.ledger.head_seq, dict(c.registry.evaluations))
            with self.subTest(decision=p.draft_contract.id), self.assertRaisesRegex(TemporalIntegrityError, "unknown metric"):
                lifecycle.reevaluate_decision(c, decisions=registry, later_world_evidence=evidence, world_time=world_time)
            self.assertEqual((c.ledger.head_seq, c.registry.evaluations), before)

    def test_explicit_world_inputs_obey_registered_ranges_units_and_windows(self):
        registry = registered_decisions()
        evidence = d205_later_evidence()
        self.assertTrue(all(record.temporal_reference.effective_at() == T1 > T0 for record in evidence))
        self.assertEqual({record.observations[0].metric_key for record in evidence},
                         {metric.key for metric in d205_profile().metric_specs})
        self.assertTrue(all(record.observations[0].window_days == 1 for record in evidence))
        observation = evidence[0].observations[0]
        for invalid in (replace(observation, value=-0.1), replace(observation, value=1.1),
                        replace(observation, value=float("nan")), replace(observation, unit="percent"),
                        replace(observation, window_days=-1)):
            c = lifecycle.complete_decision_capture(prepare(registry), decisions=registry, capture_answer=CaptureAnswer.YES)
            before = c.ledger.head_seq
            with self.subTest(observation=invalid), self.assertRaises(TemporalIntegrityError):
                lifecycle.reevaluate_decision(c, decisions=registry,
                                             later_world_evidence=(replace(evidence[0], observations=(invalid,)), evidence[1]), world_time=T1)
            self.assertEqual(c.ledger.head_seq, before)

    def test_declarations_cannot_cross_case_session_profile_or_question(self):
        registry = registered_decisions()
        first, second = golden_loop.prepare_golden_capture(), prepare(registry)
        for source, destination, time in ((first, second, golden_loop.T0), (second, first, T0)):
            declaration = make_structured_capture_declaration(
                session=source.session, gap=source.critical_gaps[0], answer=CaptureAnswer.YES,
                answered_at=time - timedelta(seconds=1),
            )
            with self.assertRaises(ValueError):
                declaration_to_evidence(declaration=declaration, session=destination.session,
                                        gap=destination.critical_gaps[0], evidence_id="REJECTED")
            before = destination.ledger.head_seq
            with self.assertRaises(ValueError):
                lifecycle.complete_decision_capture(
                    replace(destination, session=source.session), decisions=registry, capture_answer=CaptureAnswer.YES,
                )
            self.assertEqual(destination.ledger.head_seq, before)

    def test_changed_instance_source_profile_hash_and_unknown_decision_fail_closed(self):
        registry = registered_decisions()
        p = prepare(registry)
        corruptions = (
            replace(p, assignment=replace(p.assignment, profile_hash="incorrect")),
            replace(p, observable=replace(p.observable, sources=(replace(p.observable.sources[0], content="changed"), *p.observable.sources[1:]))),
        )
        for bad in corruptions:
            with self.assertRaises(ValueError):
                lifecycle.complete_decision_capture(bad, decisions=registry, capture_answer=CaptureAnswer.YES)
        with self.assertRaisesRegex(ValueError, "unknown registered decision"):
            registry.resolve("TEST-306")
        profile, instance, identity = registry.resolve("D-205")
        changed_registry = DecisionRegistry(profiles=(profile,), instances=(replace(instance, decision_time=T0 + timedelta(seconds=1)),), identities=((instance.decision_id, identity),))
        with self.assertRaises(ValueError):
            lifecycle.complete_decision_capture(p, decisions=changed_registry, capture_answer=CaptureAnswer.YES)

    def test_runtime_ledgers_registries_and_authority_are_isolated(self):
        registry = registered_decisions()
        p1, p2 = golden_loop.prepare_golden_capture(), prepare(registry)
        before = tuple(p1.ledger.entries_as_of(p1.ledger.head_seq))
        c2 = lifecycle.complete_decision_capture(p2, decisions=registry, capture_answer=CaptureAnswer.YES)
        self.assertEqual(tuple(p1.ledger.entries_as_of(p1.ledger.head_seq)), before)
        c1 = lifecycle.complete_decision_capture(p1, decisions=registry, capture_answer=CaptureAnswer.YES)
        self.assertIsNot(c1.ledger, c2.ledger)
        self.assertIsNot(c1.registry, c2.registry)
        self.assertTrue(set(c1.registry.commits).isdisjoint(c2.registry.commits))
        self.assertTrue(set(c1.registry.authorizations).isdisjoint(c2.registry.authorizations))
        self.assertEqual(prepare(registry).established_relation_ids, frozenset(("R201",)))

    def test_both_cases_execute_same_production_functions_and_canonical_engine(self):
        for run in (golden_loop.run_golden_decision, d205_run):
            calls = set()
            def trace(frame, event, arg):
                if event == "call":
                    calls.add((frame.f_globals.get("__name__"), frame.f_code.co_name))
            old = sys.getprofile()
            try:
                sys.setprofile(trace)
                run()
            finally:
                sys.setprofile(old)
            for name in ("prepare_decision", "complete_decision_capture", "reevaluate_decision"):
                self.assertIn((lifecycle.__name__, name), calls)
            for name in ("bind", "select_critical_gaps", "plan_questions"):
                self.assertIn(("decision_recall.product.capture", name), calls)
            self.assertIn(("decision_recall.engine", "evaluate_target"), calls)
            self.assertIn(("decision_recall.m21_strict", "strict_verify_full_replay"), calls)

    def test_contract_rebinding_and_all_references_are_independent_of_d104(self):
        profile, instance, _ = registered_decisions().resolve("D-205")
        contract = profile.contract(instance)
        self.assertEqual(contract.id, "D-205")
        self.assertEqual({r.object_id for r in contract.historical_relations}, {"D-205"})
        self.assertEqual({r.subject_id for r in contract.historical_relations}, {c.id for c in contract.claims})
        self.assertEqual({b.historical_relation_id for b in (*profile.target.changed_bindings, *profile.target.surviving_bindings)}, {r.id for r in contract.historical_relations})
        self.assertEqual({b.current_match_rule_id for b in (*profile.target.changed_bindings, *profile.target.surviving_bindings)}, {r.id for r in contract.current_match_rules})
        self.assertEqual(profile.target.revisit_rule_ids, tuple(r.id for r in contract.revisit_rules))
        comp = contract.composition(profile.target.limiting_composition_id)
        self.assertEqual(comp.target_ref, profile.target.ref)
        self.assertEqual(comp.relation_ids, ("R202",))
        self.assertEqual({r.premise_id for r in contract.current_match_rules}, {c.id for c in contract.claims})
        metrics = {m.key for m in profile.metric_specs}
        self.assertTrue(all(r.condition.metric_key in metrics for r in (*contract.current_match_rules, *contract.revisit_rules)))
        text = json.dumps((asdict(contract), asdict(profile.target)), default=str)
        for forbidden in ("D-104", "Apex", "Beacon", "apex_", "beacon_", "ROLLBACK_CONTEXT"):
            self.assertNotIn(forbidden, text)

    def test_third_case_is_only_configuration_data_entering_real_registry(self):
        # TEST-306 is never added to the product registry. No new lifecycle/compiler.
        def rename(text):
            return text.replace("D-205", "TEST-306").replace("Orion v42", "Lyra v9").replace("Orion v41", "Lyra v8").replace("5%", "4%")
        base_profile, base_instance, _ = registered_decisions().resolve("D-205")
        profile = replace(
            base_profile, id="TEST_RELEASE_RECOVERY",
            contract_definition=replace(base_profile.contract_definition, action="rollback_lyra_v9_to_v8",
                                        claims=tuple(replace(c, evidence_refs=tuple(ref.replace("D205", "TEST306") for ref in c.evidence_refs)) for c in base_profile.contract_definition.claims)),
            fact_displays=tuple(replace(d, quote=rename(d.quote)) for d in base_profile.fact_displays),
            decision_display=rename(base_profile.decision_display),
        )
        instance = replace(base_instance, decision_id="TEST-306", profile_id=profile.id,
                           source_records=tuple(replace(s, content=rename(s.content)) for s in base_instance.source_records))
        registry = DecisionRegistry(profiles=(profile,), instances=(instance,), identities=((instance.decision_id, ProductIdentity("COMMIT-TEST306", "EVAL-TEST306", "TEST306-V1")),))
        compiler = ExactSpanFixtureCompiler(tuple((key, kind, sid, rename(quote)) for key, kind, sid, quote in D205_CANDIDATE_FIXTURE))
        evidence = []
        for record, value, text in zip(d205_later_evidence(), (0.04, 1.0), (
            "A supplied one-day Lyra v9 validation reports a 4% request error rate.",
            "A supplied one-day Lyra v8 rehearsal restored every attempt.",
        )):
            evidence.append(replace(record, id=record.id.replace("D205", "TEST306"), content=text,
                                    source_content_hash=source_hash(text), observations=(replace(record.observations[0], value=value),)))
        p, c, result = execute(registry, instance.decision_id, compiler, tuple(evidence), T1)
        self.assertIn("Lyra v8", p.critical_gaps[0].question)
        self.assertEqual(c.commit.decision_id, "TEST-306")
        self.assertEqual(result.evaluation.canonical_result.safe_reuse_result, "reuse_authorized")
        self.assertEqual(result.evaluation.canonical_result.reason_codes, ("NO_TARGET_SUPPORT_INVALIDATION",))
        self.assertEqual(c.materialized_contract.composition("C201").value, CompositionValue.NOT_DURABLY_RECORDED)
        self.assertEqual(result.replayed_result, result.evaluation.canonical_result)

    def test_shared_modules_have_no_domain_dispatch_and_config_has_no_outcome(self):
        for module in (lifecycle, definitions):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                    condition = getattr(node, "test", getattr(node, "subject", None))
                    text = ast.unparse(condition)
                    for forbidden in ("D-104", "D-205", "Supplier", "Apex", "Beacon", "Orion", "rollback"):
                        self.assertNotIn(forbidden, text)
        for obj in (d205_profile(), d205_instance()):
            names = {f.name for f in fields(obj)}
            self.assertTrue(names.isdisjoint({"expected_result", "safe_reuse_result", "approved_answer", "authority_policy", "provenance_type"}))
            self.assertFalse(any(callable(getattr(obj, f.name)) for f in fields(obj)))


if __name__ == "__main__":
    unittest.main()
