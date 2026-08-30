"""Real HTTP → production candidates → shared lifecycle → engine/strict replay."""
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import inspect
import json
from threading import Thread
from textwrap import dedent
import unittest
from unittest.mock import patch

from decision_recall import engine, m21_strict
from decision_recall.domain import ProvenanceType
from decision_recall.temporal import LedgerEntryKind, source_hash
from decision_recall.product import case_api, configured_candidates, lifecycle
from decision_recall.product.candidate_plans import registered_candidate_plans
from decision_recall.product.cloudrun_server import DecisionRecallHandler, handler_for_cases
from decision_recall.product.definitions import DecisionRegistry, ProductIdentity
from decision_recall.product.registered_decisions import registered_decisions


BINDING_FIELDS = ("decision_id", "capture_session_id", "profile_hash", "gap_id", "question_hash")


def capture_payload(preparation):
    return {**{key: preparation[key] for key in BINDING_FIELDS}, "answer": "yes"}


def example_input(preparation):
    # Client observation data only; these values are never product configuration.
    samples = {
        "D-104": ("2026-10-04T09:00:00+00:00", {"apex_on_time_rate": 0.987, "beacon_reactivation_days": 70}),
        "D-205": ("2026-09-08T12:00:00+00:00", {"release_error_rate": 0.06, "rollback_restore_success_rate": 0.8}),
    }
    time, values = samples[preparation["decision_id"]]
    return {"capture": capture_payload(preparation), "world_time": time, "observations": [
        {"metric_key": spec["metric_key"], "value": values[spec["metric_key"]], "unit": spec["unit"],
         "window_days": spec["minimum_window_days"], "observed_at": time}
        for spec in preparation["metric_schema"]
    ]}


@contextmanager
def serving(handler=DecisionRecallHandler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(address, method, path, payload=None, *, raw=None, headers=None):
    connection = HTTPConnection(*address, timeout=10)
    body = raw if raw is not None else json.dumps(payload) if payload is not None else None
    try:
        connection.request(method, path, body=body.encode("utf-8") if body is not None else None,
                           headers=headers or {"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


class RegisteredCaseHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serving()
        cls.address = cls.server.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def call(self, method, case_id=None, operation=None, payload=None, **kwargs):
        path = "/api/cases" if case_id is None else f"/api/cases/{case_id}/{operation}"
        return request(self.address, method, path, payload, **kwargs)

    def preparation(self, case_id):
        status, data = self.call("GET", case_id, "capture-preparation")
        self.assertEqual(status, 200, data)
        return data

    def test_listing_and_preparation_share_truthful_bounded_schema(self):
        status, listing = self.call("GET")
        self.assertEqual(status, 200)
        self.assertEqual([item["decision_id"] for item in listing["cases"]], ["D-104", "D-205"])
        first, second = self.preparation("D-104"), self.preparation("D-205")
        self.assertEqual(first.keys(), second.keys())
        for data in (first, second):
            self.assertEqual(data["candidate_source_mode"], "configured_mechanically_grounded_example_candidates")
            self.assertEqual(data["observation_source_mode"], "supplied_current_example_record")
            self.assertEqual(data["status"], "issued")
            self.assertEqual(len(data["known_facts"]), 2)
            self.assertEqual(len(data["source_records"]), 3)
            states = {r["relation_id"]: r["knowledge_state"] for r in data["historical_relations"]}
            self.assertEqual(states[data["unresolved_relation_id"]], "not_durably_recorded")
            for key in ("expected_result", "approved_answer", "safe_reuse_result", "world_time", "evaluation_hash", "observations"):
                self.assertNotIn(key, data)
            for spec in data["metric_schema"]:
                self.assertNotIn("threshold", spec)
        self.assertEqual({s["metric_key"] for s in first["metric_schema"]}, {"apex_on_time_rate", "beacon_reactivation_days"})
        status, legacy = request(self.address, "GET", "/api/capture-preparation")
        self.assertEqual(status, 200)
        self.assertEqual(first["question"], legacy["question"])
        self.assertEqual(first["question_hash"], legacy["question_hash"])

    def test_both_cases_http_capture_and_real_engine_reevaluation(self):
        result_shapes = []
        for case_id, expected, relation in (("D-104", "insufficient_evidence", "R2"),
                                           ("D-205", "reuse_not_authorized", "R202")):
            with self.subTest(case=case_id):
                with patch.object(case_api, "prepare_decision", wraps=lifecycle.prepare_decision) as prepare_spy, \
                     patch.object(m21_strict, "evaluate_target", wraps=engine.evaluate_target) as evaluate_spy, \
                     patch.object(lifecycle, "strict_verify_full_replay", wraps=m21_strict.strict_verify_full_replay) as replay_spy:
                    p = self.preparation(case_id)
                    status, capture = self.call("POST", case_id, "capture", capture_payload(p))
                    self.assertEqual(status, 200, capture)
                    self.assertEqual(capture["status"], "capture_verified")
                    self.assertEqual({r["relation_id"]: r["knowledge_state"] for r in capture["historical_relations"]}[relation], "established")
                    self.assertEqual(capture["future_evaluation_status"], "not_run")
                    self.assertNotIn("evaluation_hash", capture)
                    status, result = self.call("POST", case_id, "reevaluate", example_input(p))
                    self.assertEqual(status, 200, result)
                    self.assertEqual(result["safe_reuse_result"], expected)
                    self.assertEqual(result["evaluation_hash"], result["replay_hash"])
                    self.assertEqual(len(result["evaluation_hash"]), 64)
                    self.assertEqual({r["relation_id"]: r["knowledge_state"] for r in result["historical_relations"]}[relation], "established")
                    self.assertEqual(result["compositions"][0]["value"], "not_durably_recorded")
                    self.assertTrue(evaluate_spy.called)
                    self.assertTrue(replay_spy.called)
                    self.assertEqual(prepare_spy.call_count, 3)
                    for call in prepare_spy.call_args_list:
                        self.assertIs(type(call.kwargs["compiler"]), configured_candidates.ConfiguredCandidateCompiler)
                result_shapes.append(result.keys())
        self.assertEqual(len(result_shapes), 2)
        self.assertEqual(result_shapes[0], result_shapes[1])

    def test_alternative_numeric_input_changes_canonical_outcome_not_policy(self):
        p = self.preparation("D-205")
        payload = example_input(p)
        status, before = self.call("POST", "D-205", "reevaluate", payload)
        self.assertEqual(status, 200)
        payload["observations"][1]["value"] = 1.0
        status, after = self.call("POST", "D-205", "reevaluate", payload)
        self.assertEqual(status, 200, after)
        self.assertEqual(before["safe_reuse_result"], "reuse_not_authorized")
        self.assertEqual(after["safe_reuse_result"], "reuse_authorized")
        self.assertEqual(after["reason_codes"], ["NO_TARGET_SUPPORT_INVALIDATION"])
        self.assertEqual(after["current_matches"], {"M201": "matches", "M202": "matches"})
        self.assertNotEqual(before["evaluation_hash"], after["evaluation_hash"])
        self.assertEqual(after["evaluation_hash"], after["replay_hash"])
        self.assertEqual(before["historical_relations"], after["historical_relations"])
        self.assertEqual(before["compositions"], after["compositions"])
        self.assertEqual(before["profile_id"], after["profile_id"])

    def test_capture_contains_no_t1_and_reconstruction_does_not_retain_user_state(self):
        for case_id in ("D-104", "D-205"):
            p = self.preparation(case_id)
            with patch.object(case_api, "reevaluate_decision", side_effect=AssertionError("capture cannot enter T1")), \
                 patch.object(case_api, "complete_decision_capture", wraps=lifecycle.complete_decision_capture) as complete_spy:
                status, result = self.call("POST", case_id, "capture", capture_payload(p))
                self.assertEqual(status, 200, result)
                self.assertEqual(complete_spy.call_count, 1)
            for key in ("world_time", "current_matches", "safe_reuse_result", "limiting_requirements", "reason_codes", "evaluation_hash", "replay_hash"):
                self.assertNotIn(key, result)
            self.assertEqual(self.preparation(case_id), p)

    def test_wrong_binding_and_cross_case_captures_rejected_before_completion(self):
        preparations = [self.preparation(c) for c in ("D-104", "D-205")]
        with patch.object(case_api, "complete_decision_capture", side_effect=AssertionError("must not complete")):
            for p, other in zip(preparations, reversed(preparations)):
                for key in BINDING_FIELDS:
                    payload = capture_payload(p)
                    payload[key] += "-wrong"
                    with self.subTest(case=p["decision_id"], field=key):
                        status, _ = self.call("POST", p["decision_id"], "capture", payload)
                        self.assertEqual(status, 409)
                        reevaluation = example_input(p)
                        reevaluation["capture"] = payload
                        self.assertEqual(self.call("POST", p["decision_id"], "reevaluate", reevaluation)[0], 409)
                self.assertEqual(self.call("POST", p["decision_id"], "capture", capture_payload(other))[0], 409)

    def test_capture_rejects_unsupported_answers_and_authority_overrides(self):
        for case_id in ("D-104", "D-205"):
            payload = capture_payload(self.preparation(case_id))
            for answer in ("no", "skip", "not_sure", "YES", True, None, {}, "yes "):
                self.assertEqual(self.call("POST", case_id, "capture", {**payload, "answer": answer})[0], 400)
            for key in ("profile_id", "profile_version", "policy", "authority", "knowledge_state", "composition_state",
                        "target", "provenance_type", "safe_reuse_result", "authorized", "expected_result", "optional_note"):
                with self.subTest(case=case_id, key=key):
                    self.assertEqual(self.call("POST", case_id, "capture", {**payload, key: "forged"})[0], 400)
            for key in payload:
                bad = {k: v for k, v in payload.items() if k != key}
                self.assertEqual(self.call("POST", case_id, "capture", bad)[0], 400)

    def test_unknown_cases_and_routes_never_fall_back_to_hero(self):
        p = self.preparation("D-104")
        for op, method, payload in (("capture-preparation", "GET", None), ("capture", "POST", capture_payload(p)),
                                    ("reevaluate", "POST", example_input(p))):
            self.assertEqual(self.call(method, "UNKNOWN", op, payload)[0], 404)
        self.assertEqual(self.call("GET", "D-104", "not-a-route")[0], 404)
        self.assertEqual(self.call("POST")[0], 405)
        self.assertEqual(self.call("GET", "D-104", "capture")[0], 405)
        self.assertEqual(self.call("POST", "D-104", "capture-preparation", {})[0], 405)

    def test_required_metrics_ranges_units_windows_and_timestamps(self):
        for case_id in ("D-104", "D-205"):
            p = self.preparation(case_id)
            base = example_input(p)
            invalid = [
                ("metric_key", "unconfigured"), ("metric_key", []), ("value", True),
                ("value", "0.5"), ("value", None), ("value", float("nan")),
                ("value", float("inf")), ("value", -0.1), ("value", 1.1),
                ("unit", "percent"), ("window_days", 0), ("window_days", -1),
                ("window_days", True), ("window_days", 1.5), ("window_days", None),
                ("observed_at", p["decision_time"]), ("observed_at", "2000-01-01T00:00:00Z"),
                ("observed_at", "2099-01-01T00:00:00Z"), ("observed_at", "bad"),
                ("observed_at", "2026-09-08T12:00:00"), ("observed_at", {}),
            ]
            for key, value in invalid:
                with self.subTest(case=case_id, field=key, value=value):
                    bad = deepcopy(base)
                    bad["observations"][0][key] = value
                    self.assertEqual(self.call("POST", case_id, "reevaluate", bad)[0], 400)
            for observations in ([], base["observations"][:1], [base["observations"][0]] * 2, {}, None):
                self.assertEqual(self.call("POST", case_id, "reevaluate", {**base, "observations": observations})[0], 400)
            for time in (p["decision_time"], "2020-01-01T00:00:00Z", "2026-09-08", "invalid", None):
                self.assertEqual(self.call("POST", case_id, "reevaluate", {**base, "world_time": time})[0], 400)
        short = example_input(self.preparation("D-104"))
        short["observations"][0]["window_days"] = 29
        self.assertEqual(self.call("POST", "D-104", "reevaluate", short)[0], 400)

    def test_no_caller_evidence_identity_provenance_or_semantic_output(self):
        forbidden = ("evidence_id", "source_id", "source_content_hash", "source_span", "content", "provenance_type",
                     "authorization_id", "ledger_id", "threshold", "target", "authority", "current_matches",
                     "safe_reuse_result", "reason_codes", "profile_version", "source", "result")
        for case_id in ("D-104", "D-205"):
            base = example_input(self.preparation(case_id))
            for key in forbidden:
                with self.subTest(case=case_id, key=key):
                    bad = deepcopy(base)
                    bad["observations"][0][key] = "forged"
                    self.assertEqual(self.call("POST", case_id, "reevaluate", bad)[0], 400)
                    self.assertEqual(self.call("POST", case_id, "reevaluate", {**base, key: "forged"})[0], 400)

    def test_server_constructs_evidence_and_no_t1_exists_before_explicit_evaluation(self):
        p = self.preparation("D-205")
        payload = example_input(p)
        received = []

        def observe(completion, **kwargs):
            kinds = {e.kind for e in completion.ledger.entries_as_of(completion.ledger.head_seq)}
            self.assertTrue(kinds.isdisjoint({LedgerEntryKind.RAW_WORLD_EVIDENCE,
                                             LedgerEntryKind.WORLD_EVENT_AUTHORIZATION, LedgerEntryKind.EVALUATION}))
            self.assertEqual(completion.registry.evaluations, {})
            received.extend(kwargs["later_world_evidence"])
            return lifecycle.reevaluate_decision(completion, **kwargs)

        with patch.object(case_api, "reevaluate_decision", side_effect=observe):
            status, result = self.call("POST", "D-205", "reevaluate", payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(len(received), len(payload["observations"]))
        self.assertEqual({r.id for r in received}, {r["evidence_id"] for r in result["admitted_observations"]})
        for record in received:
            self.assertEqual(record.source_id, "supplied_current_example_record")
            self.assertEqual(record.source_content_hash, source_hash(record.content))
            self.assertIs(record.provenance_type, ProvenanceType.CONTEMPORANEOUS_RECORD)
            self.assertEqual(record.source_span, "complete server-rendered supplied observation")
            content = json.loads(record.content)
            self.assertEqual(content["decision_id"], p["decision_id"])
            self.assertEqual(content["metric_key"], record.observations[0].metric_key)
            self.assertEqual(content["value"], record.observations[0].value)

    def test_cross_case_metric_sets_rejected_even_with_correct_capture(self):
        first, second = [example_input(self.preparation(c)) for c in ("D-104", "D-205")]
        for destination, other in ((first, second), (second, first)):
            bad = {**destination, "observations": other["observations"]}
            self.assertEqual(self.call("POST", destination["capture"]["decision_id"], "reevaluate", bad)[0], 400)

    def test_observation_order_is_deterministic_and_requests_are_isolated(self):
        p = self.preparation("D-205")
        payload = example_input(p)
        status, before = self.call("POST", "D-205", "reevaluate", payload)
        self.assertEqual(status, 200)
        payload["observations"].reverse()
        status, after = self.call("POST", "D-205", "reevaluate", payload)
        self.assertEqual(status, 200)
        self.assertEqual(before, after)
        for item in after["admitted_observations"]:
            self.assertTrue(item["evidence_id"].startswith("WE-SUPPLIED-"))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.call, "POST", "D-205", "reevaluate", payload) for _ in range(2)]
            self.assertEqual([future.result() for future in futures], [(200, after)] * 2)
        self.assertEqual(self.preparation("D-205"), p)

    def test_json_body_limits_types_duplicate_fields_and_nonfinite_numbers(self):
        for raw in ("not json", "[]", "null", '{"capture":{},"capture":{}}', '{"x":NaN}', "[" * 1100 + "]" * 1100):
            self.assertEqual(self.call("POST", "D-205", "reevaluate", raw=raw)[0], 400)
        # Over-limit bodies must be rejected from headers without waiting for or
        # allocating the body (also proves a slow sender cannot bypass the limit).
        for operation, size in (("reevaluate", 12289), ("capture", 4097)):
            self.assertEqual(self.call("POST", "D-205", operation, headers={
                "Content-Type": "application/json", "Content-Length": str(size),
            })[0], 413)
        self.assertEqual(self.call("POST", "D-205", "capture", raw="{}")[0], 400)
        self.assertEqual(self.call("POST", "D-205", "capture", raw="{}", headers={"Content-Type": "text/plain"})[0], 400)

    def test_test_only_third_case_uses_same_handler_provider_and_projection(self):
        definition, instance, _ = registered_decisions().resolve("D-205")
        def rename(text):
            return text.replace("D-205", "TEST-306").replace("Orion v42", "Lyra v9").replace("Orion v41", "Lyra v8").replace("5%", "4%")
        definition = replace(definition, id="TEST_RELEASE_RECOVERY",
            contract_definition=replace(definition.contract_definition, action="rollback_lyra_v9_to_v8",
                claims=tuple(replace(c, evidence_refs=tuple(ref.replace("D205", "TEST306") for ref in c.evidence_refs)) for c in definition.contract_definition.claims)),
            fact_displays=tuple(replace(d, quote=rename(d.quote)) for d in definition.fact_displays),
            decision_display=rename(definition.decision_display))
        instance = replace(instance, decision_id="TEST-306", profile_id=definition.id,
                           source_records=tuple(replace(s, content=rename(s.content)) for s in instance.source_records))
        registry = DecisionRegistry(profiles=(definition,), instances=(instance,),
                                    identities=((instance.decision_id, ProductIdentity("COMMIT-TEST306", "EVAL-TEST306", "TEST306-V1")),))
        plan = replace(registered_candidate_plans()[1], decision_id=instance.decision_id, profile_id=definition.id,
                       candidates=tuple(replace(c, exact_quote=rename(c.exact_quote)) for c in registered_candidate_plans()[1].candidates))
        api = case_api.RegisteredCaseAPI(decisions=registry, candidate_plans=(plan,))
        with serving(handler_for_cases(api)) as address:
            status, listing = request(address, "GET", "/api/cases")
            self.assertEqual(status, 200)
            self.assertEqual([item["decision_id"] for item in listing["cases"]], ["TEST-306"])
            status, p = request(address, "GET", "/api/cases/TEST-306/capture-preparation")
            self.assertEqual(status, 200, p)
            self.assertIn("Lyra v8", p["question"])
            self.assertEqual(p.keys(), self.preparation("D-205").keys())
            self.assertEqual(request(address, "POST", "/api/cases/TEST-306/capture", capture_payload(p))[0], 200)
            payload = {"capture": capture_payload(p), "world_time": "2026-09-08T12:00:00Z", "observations": [
                {"metric_key": s["metric_key"], "value": value, "unit": s["unit"], "window_days": s["minimum_window_days"], "observed_at": "2026-09-08T12:00:00Z"}
                for s, value in zip(p["metric_schema"], (0.04, 1.0))]}
            status, result = request(address, "POST", "/api/cases/TEST-306/reevaluate", payload)
            self.assertEqual(status, 200, result)
            self.assertEqual(result["safe_reuse_result"], "reuse_authorized")
            self.assertEqual(result["evaluation_hash"], result["replay_hash"])
            self.assertEqual(result["compositions"][0]["value"], "not_durably_recorded")
        self.assertEqual(self.call("GET", "TEST-306", "capture-preparation")[0], 404)
        self.assertEqual([c["decision_id"] for c in self.call("GET")[1]["cases"]], ["D-104", "D-205"])

    def test_generic_logic_has_no_case_constants_or_outcome_branch(self):
        sources = (inspect.getsource(case_api.RegisteredCaseAPI), inspect.getsource(configured_candidates),
                   inspect.getsource(DecisionRecallHandler._handle_cases))
        for source in sources:
            tree = ast.parse(dedent(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for forbidden in ("D-104", "D-205", "TEST-306", "Apex", "Beacon", "Orion", "R202", "C201", "reuse_authorized", "insufficient_evidence"):
                        self.assertNotIn(forbidden, node.value)


if __name__ == "__main__":
    unittest.main()
