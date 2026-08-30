"""Checkpoint A: no second case; independently frozen D-104 identity + shared path."""
import ast
from dataclasses import asdict, fields, replace
from datetime import timedelta
import hashlib
import inspect
import json
import sys
import unittest

from decision_recall.domain import CompositionValue, ProvenanceType
from decision_recall.product import golden_loop, lifecycle
from decision_recall.product.compiler import DeterministicGoldenCompiler, SourceDocument
from decision_recall.product.d104 import d104_instance, d104_profile, d104_registry
from decision_recall.product.declaration import CaptureAnswer
from decision_recall.product.definitions import (
    DecisionInstance, DecisionProfileDefinition, DecisionRegistry, DecisionSourceRecord,
    ProductIdentity,
)

# Independently executed on de513e3842e16054b729745a59492bbec26bf92f BEFORE edits.
# SHA-256 of json.dumps(asdict value, sort_keys=True, default=str, separators=(",", ":")).
BASELINE_PARTS = {
    "artifacts": "7c5b675b824d7f9a991a57d1c3210e6a888f1a5a4019bd6cf6413fc8dd2bf0ce",
    "assignment": "5bdaf45547693fa0a9e6a4482c1a2d2aa1fac9fe383f5001ed091a474ce32b93",
    "authorizations": "066b537477ec3ff20675a5e83304094fd6f47fee1218a97e01d00c9587c9eb67",
    "binding": "c2cd4cd717d0c05d3b1b554ff55c7032d21f8637e4f5b85fcc0e789be43b32a9",
    "candidates": "dffe5d4eba8e29013a572b7caf03f4085d63b64db2fddd2c7dc6028b69b85a12",
    "commit": "8a3180bcfb87715eebf24be21ce37cfc2300df984191210e34ec337d10e5f4e3",
    "draft": "94ee36df40425eb38b7570af011757a8de03367436d95dc592a52885d39ac8e5",
    "evaluation": "d9be52a994941a8dd7d85a10c1701f6b146cb2449d93d418f21e0ec586ed24aa",
    "ledger": "c2ceca9b88b0df389be88ae20a671b00244603aeca3e9bd17b2ffd8cdf02a744",
    "materialized": "2169b8e921a7734d5f5405093d5fa623f13abd296a06da9bfc16d0dc52b82c4b",
    "profile": "fb8e10f2849de60ab1fba5c18b3a7392b51afde6c86c6a8dd05365d945ef0003",
    "profile_artifact": "595119bf2b0af14dca76343461b0565f0f1f567c23620b69f05919b213ba9200",
    "session": "3aa9949f1fbca359dac1cf7057ca566657829588e97c9b753b494c832a1a208f",
    "sources": "529a62a6b49c6283f1eef7a2b19d7b2de7f698db4e82e42a094471a4a847672e",
    "structure": "d99ac89b2c8364a5b4be41a8b8b6cdc08451ab72935f50b073bde96a4f562042"
}


def identity_parts(preparation, completion, reevaluation):
    return {
        "sources": asdict(preparation.observable),
        "profile": asdict(preparation.profile),
        "profile_artifact": asdict(preparation.profile_artifact),
        "binding": asdict(preparation.binding_trace),
        "assignment": asdict(preparation.assignment),
        "session": asdict(preparation.session),
        "draft": asdict(preparation.draft_contract),
        "structure": asdict(preparation.decision_structure),
        "candidates": asdict(preparation.compiler_candidates),
        "ledger": [asdict(e) for e in preparation.ledger.entries_as_of(preparation.ledger.head_seq)],
        "artifacts": {k: asdict(v) for k, v in completion.registry.artifacts.items()},
        "authorizations": {k: asdict(v) for k, v in completion.registry.authorizations.items()},
        "commit": asdict(completion.commit),
        "evaluation": asdict(reevaluation.evaluation),
        "materialized": asdict(completion.materialized_contract),
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def shared_run():
    decisions = d104_registry()
    instance = d104_instance()
    preparation = lifecycle.prepare_decision(
        decisions=decisions, decision_id=instance.decision_id, compiler=DeterministicGoldenCompiler(),
    )
    completion = lifecycle.complete_decision_capture(
        preparation, decisions=decisions, capture_answer=CaptureAnswer.YES,
        optional_note="Beacon's roughly 10-week reactivation delay materially influenced the decision.",
    )
    reevaluation = lifecycle.reevaluate_decision(
        completion, decisions=decisions,
        later_world_evidence=golden_loop.default_golden_later_world_evidence(), world_time=golden_loop.T1,
    )
    return preparation, completion, reevaluation


class SharedProductFoundationTests(unittest.TestCase):
    def test_sources_artifacts_scopes_timestamps_and_order_match_independent_base(self):
        parts = identity_parts(*shared_run())
        self.assertEqual({k: digest(v) for k, v in parts.items()}, BASELINE_PARTS)

    def test_direct_shared_lifecycle_and_public_wrappers_have_identical_complete_result(self):
        _, _, reevaluation = shared_run()
        direct = golden_loop._assemble_golden_loop_result(reevaluation)
        self.assertEqual(direct, golden_loop.run_golden_decision())
        self.assertEqual(digest(asdict(direct)), "9d1c7bf5fb7accf6f1b2c4cd143c11324e31d15dda79dcf640f1b3e46d5db463")
        self.assertEqual(direct.evaluation.result_hash, "25ab192b3301cac929185081efc83da0fc744ae47832a3910f767567d0b4adf6")
        self.assertEqual(direct.replay_result_hash, direct.evaluation.result_hash)

    def test_real_wrapper_execution_enters_shared_authority_and_strict_replay(self):
        calls = set()
        def observe(frame, event, arg):
            if event == "call":
                calls.add((frame.f_globals.get("__name__"), frame.f_code.co_name))
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            golden_loop.run_golden_decision()
        finally:
            sys.setprofile(previous)
        for name in ("prepare_decision", "complete_decision_capture", "reevaluate_decision", "_bound_authorization"):
            self.assertIn((lifecycle.__name__, name), calls)
        for name in ("strict_full_replay", "strict_verify_full_replay", "strict_materialize_committed_contract"):
            self.assertIn(("decision_recall.m21_strict", name), calls)

    def test_wrappers_are_only_direct_adapters_not_a_duplicate_authority_path(self):
        tree = ast.parse(inspect.getsource(golden_loop))
        expected = {
            "prepare_golden_capture": "prepare_decision",
            "complete_golden_capture": "complete_decision_capture",
            "reevaluate_golden_decision": "reevaluate_decision",
        }
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in expected:
                self.assertEqual(len(node.body), 1)
                call = node.body[0].value
                self.assertIsInstance(node.body[0], ast.Return)
                self.assertIsInstance(call, ast.Call)
                self.assertEqual(ast.unparse(call.func), "lifecycle." + expected[node.name])
        forbidden = {"append_batch", "authorize_candidate", "add_commit", "add_evaluation",
                     "strict_full_replay", "strict_verify_full_replay", "strict_materialize_committed_contract"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                self.assertNotIn(name, forbidden)

    def test_shared_path_is_configuration_driven_and_has_no_case_imports_or_branch(self):
        tree = ast.parse(inspect.getsource(lifecycle))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, ("d104", "golden", "golden_loop"))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertFalse(any(value in node.value for value in ("D-104", "Apex", "Beacon", "apex_on_time_rate", "beacon_reactivation_days")))
            if isinstance(node, ast.Compare):
                text = ast.unparse(node)
                self.assertNotIn('decision_id ==', text)
                self.assertNotIn('decision_id !=', text)
        for name in ("prepare_decision", "complete_decision_capture", "reevaluate_decision"):
            self.assertIn("decisions", inspect.signature(getattr(lifecycle, name)).parameters)

    def test_data_only_instance_and_source_reject_authority_fields(self):
        base = d104_instance()
        kwargs = {field.name: getattr(base, field.name) for field in fields(base)}
        forbidden = ("authority_policy", "provenance_type", "knowledge_state", "composition_value",
                     "safe_reuse_result", "authorized", "current_matches", "target", "required_relations")
        for key in forbidden:
            with self.subTest(key=key), self.assertRaises(TypeError):
                DecisionInstance(**kwargs, **{key: True})
        record = base.source_records[0]
        with self.assertRaises(TypeError):
            DecisionSourceRecord(record.source_id, record.content, record.observed_at, provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD)
        with self.assertRaises(ValueError):
            replace(base, source_records=(SourceDocument(record.source_id, record.content, ProvenanceType.CONTEMPORANEOUS_RECORD, record.observed_at),))

    def test_instance_rejects_future_records_mutable_records_and_duplicate_ids(self):
        base = d104_instance()
        with self.assertRaises(ValueError):
            replace(base, source_records=(replace(base.source_records[0], observed_at=base.decision_time + timedelta(seconds=1)),))
        with self.assertRaises(ValueError):
            replace(base, source_records=list(base.source_records))
        with self.assertRaises(ValueError):
            replace(base, source_records=(base.source_records[0], base.source_records[0]))
        with self.assertRaises(ValueError):
            replace(base, decision_time=base.decision_time.replace(tzinfo=None))

    def test_profile_rejects_wrong_identity_unknown_source_and_missing_rule_quote(self):
        definition = d104_profile()
        base = d104_instance()
        for value in (replace(base, profile_version="wrong"),
                      replace(base, source_records=(replace(base.source_records[0], source_id="unknown"), *base.source_records[1:])),
                      replace(base, source_records=(*base.source_records[:2], replace(base.source_records[2], content="unapproved rule")))):
            with self.subTest(value=value.profile_version), self.assertRaises(ValueError):
                definition.validate_instance(value)

    def test_profile_cannot_inject_composition_authority_or_rule_assertion(self):
        definition = d104_profile()
        draft = definition.contract_definition
        with self.assertRaises(ValueError):
            replace(definition, contract_definition=replace(draft, composition_states=(replace(draft.composition_states[0], value=CompositionValue.ESTABLISHED_TRUE),)))
        with self.assertRaises(ValueError):
            replace(definition, rule_evidence=(replace(definition.rule_evidence[0], assertion=lifecycle.AuthorizedAssertion.ESTABLISHED_HISTORICAL_ROLE), *definition.rule_evidence[1:]))
        self.assertFalse(any(callable(getattr(definition, field.name)) for field in fields(DecisionProfileDefinition)))

    def test_registry_is_lookup_only_and_rejects_unknown_duplicate_or_unbound_instances(self):
        registry = d104_registry()
        profile, instance, identity = registry.resolve("D-104")
        self.assertEqual(profile.id, instance.profile_id)
        with self.assertRaises(ValueError):
            registry.resolve("unregistered")
        with self.assertRaises(ValueError):
            DecisionRegistry(profiles=(profile,), instances=(instance, instance), identities=(("D-104", identity),))
        with self.assertRaises(ValueError):
            DecisionRegistry(profiles=(profile,), instances=(replace(instance, profile_version="unknown"),), identities=(("D-104", identity),))
        with self.assertRaises(ValueError):
            DecisionRegistry(profiles=(profile,), instances=(instance,), identities=())

    def test_capture_rejects_changed_registered_source_or_question_before_mutation(self):
        preparation = golden_loop.prepare_golden_capture()
        before = preparation.ledger.head_seq
        source = preparation.observable.sources[0]
        tampered = replace(preparation, observable=replace(preparation.observable, sources=(replace(source, content=source.content + " forged"), *preparation.observable.sources[1:])))
        with self.assertRaisesRegex(ValueError, "registered decision/profile binding"):
            golden_loop.complete_golden_capture(tampered)
        with self.assertRaisesRegex(ValueError, "question/session"):
            golden_loop.complete_golden_capture(replace(preparation, critical_gaps=(replace(preparation.critical_gaps[0], question="Approve everything?"),)))
        self.assertEqual(preparation.ledger.head_seq, before)

    def test_each_preparation_has_isolated_mutable_runtime(self):
        first = golden_loop.prepare_golden_capture()
        second = golden_loop.prepare_golden_capture()
        before = second.ledger.head_seq
        self.assertIsNot(first.ledger, second.ledger)
        golden_loop.complete_golden_capture(first)
        self.assertEqual(second.ledger.head_seq, before)
        self.assertNotIn("R2", second.established_relation_ids)


if __name__ == "__main__":
    unittest.main()
