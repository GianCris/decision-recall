"""Production example-provider boundary; no test compiler or provider calls."""
from dataclasses import asdict, fields, replace
import unittest

from decision_recall.domain import ProvenanceType
from decision_recall.temporal import TemporalIntegrityError
from decision_recall.product.candidate_plans import registered_candidate_plans
from decision_recall.product.case_api import RegisteredCaseAPI, registered_case_api
from decision_recall.product.capture import ProfileBinder
from decision_recall.product.compiler import CandidateKind, EvidenceResolver, SemanticCandidateResolver
from decision_recall.product.configured_candidates import ConfiguredCandidateCompiler, ConfiguredCandidateSpec
from decision_recall.product.definitions import DecisionRegistry
from decision_recall.product.lifecycle import prepare_decision
from decision_recall.product.registered_decisions import registered_decisions


class ConfiguredCandidateTests(unittest.TestCase):
    def setUp(self):
        self.registry = registered_decisions()
        self.definition, self.instance, self.identity = self.registry.resolve("D-205")
        self.plan = registered_candidate_plans()[1]
        self.profile, _ = ProfileBinder().bind(template=self.definition.capture_template,
                                             structure=self.definition.structure(self.instance))
        self.observable = self.definition.observable(self.instance)

    def compile(self, plan=None, observable=None):
        return ConfiguredCandidateCompiler(plan=plan or self.plan, contract=self.definition.contract(self.instance)).compile_observable(
            observable=observable or self.observable, profile=self.profile,
        )

    def test_allowlist_has_no_authority_result_or_provenance_field(self):
        self.assertEqual({f.name for f in fields(ConfiguredCandidateSpec)},
                         {"semantic_key", "candidate_kind", "source_id", "exact_quote"})
        for key in ("entity_id", "knowledge_state", "authorization", "composition_value", "safe_reuse_result",
                    "expected_result", "provenance_type", "source_content_hash", "start", "end"):
            with self.subTest(key=key), self.assertRaises(TypeError):
                ConfiguredCandidateSpec(**asdict(self.plan.candidates[0]), **{key: "forged"})
        with self.assertRaises((AttributeError, TypeError)):
            self.plan.candidates[0].authority = True

    def test_compilation_only_returns_grounded_candidates_and_does_not_authorize(self):
        bundle = self.compile()
        self.assertEqual(bundle, self.compile())
        self.assertEqual(len(bundle.candidates), 3)
        for candidate, spec in zip(bundle.candidates, self.plan.candidates):
            self.assertEqual(self.observable.source_map()[candidate.source_id].content[candidate.start:candidate.end], spec.exact_quote)
            self.assertEqual({f.name for f in fields(candidate)},
                             {"candidate_id", "semantic_key", "kind", "source_id", "start", "end"})
        self.assertTrue(all(r.knowledge_state.value == "not_durably_recorded"
                            for r in self.definition.contract(self.instance).historical_relations))
        self.assertEqual(self.definition.target.limiting_composition_id, "C201")
        self.assertEqual(self.definition.contract_definition.composition("C201").value.value, "not_durably_recorded")

    def test_unknown_source_absent_ambiguous_quote_and_unknown_semantics_rejected(self):
        base = self.plan.candidates[0]
        for bad in (replace(base, source_id="unregistered"), replace(base, exact_quote="not in records"),
                    replace(base, semantic_key="new_fact"), replace(base, semantic_key="C201")):
            with self.subTest(candidate=bad), self.assertRaises(ValueError):
                self.compile(replace(self.plan, candidates=(bad, *self.plan.candidates[1:])))
        repeated = replace(self.observable.sources[0], content=self.observable.sources[0].content + base.exact_quote)
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.compile(observable=replace(self.observable, sources=(repeated, *self.observable.sources[1:])))

    def test_unsupported_kinds_and_human_slot_rejected_even_with_real_quote(self):
        for kind in ("fact", "composition", "authority", CandidateKind.ELICITED_HISTORICAL_ROLE):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                replace(self.plan.candidates[0], candidate_kind=kind)
        bad = replace(self.plan.candidates[1], candidate_kind=CandidateKind.HISTORICAL_ROLE,
                      semantic_key="historical_support:recovery_rehearsal_passed")
        with self.assertRaisesRegex(ValueError, "human capture slot"):
            self.compile(replace(self.plan, candidates=(*self.plan.candidates, bad)))
        bad = replace(bad, semantic_key="RECOVERY_READINESS_HISTORICAL_ROLE")
        with self.assertRaises(ValueError):
            self.compile(replace(self.plan, candidates=(*self.plan.candidates, bad)))

    def test_incomplete_duplicate_and_wrong_identity_plans_rejected(self):
        for candidates in (self.plan.candidates[:1], (*self.plan.candidates, self.plan.candidates[0])):
            with self.assertRaises(ValueError):
                self.compile(replace(self.plan, candidates=candidates))
        with self.assertRaises(ValueError):
            self.compile(replace(self.plan, decision_id="OTHER"))
        for plan in (replace(self.plan, profile_id="OTHER"), replace(self.plan, profile_version="2")):
            with self.assertRaises(ValueError):
                RegisteredCaseAPI(decisions=self.registry, candidate_plans=(plan,))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            RegisteredCaseAPI(decisions=self.registry, candidate_plans=(self.plan, self.plan))

    def test_provenance_comes_from_source_and_policy_not_candidate(self):
        candidate = self.compile().candidates[0]
        resolved = SemanticCandidateResolver().resolve(candidate=candidate, contract=self.definition.contract(self.instance), profile=self.profile)
        untrusted = replace(self.observable, sources=tuple(replace(s, provenance_type=ProvenanceType.LLM_INFERRED) for s in self.observable.sources))
        evidence = EvidenceResolver().resolve(observable=untrusted, candidate=resolved, evidence_id="CHECK")
        self.assertIs(evidence.provenance_type, ProvenanceType.LLM_INFERRED)
        definition = replace(self.definition, source_admissions=tuple(replace(s, provenance_type=ProvenanceType.LLM_INFERRED)
                                                                     for s in self.definition.source_admissions))
        registry = DecisionRegistry(profiles=(definition,), instances=(self.instance,), identities=((self.instance.decision_id, self.identity),))
        with self.assertRaises(TemporalIntegrityError):
            prepare_decision(decisions=registry, decision_id=self.instance.decision_id,
                             compiler=ConfiguredCandidateCompiler(plan=self.plan, contract=definition.contract(self.instance)))

    def test_production_preparation_derives_known_state_but_not_human_authority(self):
        data = registered_case_api().preparation("D-205")
        self.assertEqual({item["fact_id"] for item in data["known_facts"]}, {"F201", "F202"})
        self.assertEqual({item["relation_id"]: item["knowledge_state"] for item in data["historical_relations"]},
                         {"R201": "established", "R202": "not_durably_recorded"})
        self.assertEqual(data["unresolved_relation_id"], "R202")
        self.assertEqual(data["candidate_source_mode"], "configured_mechanically_grounded_example_candidates")
        with self.assertRaises(ValueError):
            ConfiguredCandidateCompiler(plan=self.plan, contract=self.definition.contract(self.instance)).compile_response()


if __name__ == "__main__":
    unittest.main()
