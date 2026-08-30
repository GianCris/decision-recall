import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

import dr_baselines.decision_premise_capture as dpc
import dr_baselines.pauto_provider_probe as probe
from dr_baselines.models import ModelResponse
from google.genai import models, types
from unittest.mock import MagicMock

class Adapter:
    identifier="probe-mock"
    def __init__(self,outcomes):self.outcomes=list(outcomes);self.calls=0
    def generate(self,*a,**k):
        self.calls+=1;v=self.outcomes.pop(0)
        if isinstance(v,Exception):raise v
        return ModelResponse(text=v)
    def close(self):pass

class StatusError(Exception):
    def __init__(self,status):self.status_code=status;super().__init__(f"HTTP {status}")

class PautoProviderProbeTests(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.out=Path(self.t.name)/"probe"
    def test_variant_ladder_exact_differences_and_fields(self):
        v=probe.provider_variants();self.assertEqual(probe.VARIANT_ORDER,("V0","V1","V2","V3"));self.assertEqual(v["V0"]["schema"],dpc.PAUTO_SCHEMA)
        d01=probe._variant_diff(v["V0"]["schema"],v["V1"]["schema"]);self.assertTrue(d01);self.assertTrue(all(path.endswith(("/minItems","/maxItems")) and kind=="removed" for path,kind in d01))
        d12=probe._variant_diff(v["V1"]["schema"],v["V2"]["schema"]);self.assertTrue(d12);self.assertTrue(all(path.endswith("/additionalProperties") and kind=="removed" for path,kind in d12))
        self.assertEqual(v["V2"]["schema"],v["V3"]["schema"]);self.assertEqual(v["V2"]["schema_input_path"],"response_json_schema");self.assertEqual(v["V3"]["schema_input_path"],"response_schema")
        for x in v.values():self.assertEqual(set(x["schema"]["properties"]),{"target_decision_id",*dpc.CATEGORIES})
        api=MagicMock();api.vertexai=True;api.project="p";api.location="global"
        for name,item in v.items():
            config=types.GenerateContentConfig(response_mime_type="application/json",**{item["schema_input_path"]:copy.deepcopy(item["schema"])})
            params=types._GenerateContentParameters(model=dpc.MODEL_ID,contents="synthetic",config=config)
            body=models._GenerateContentParameters_to_vertex(api,params,None,params)
            self.assertIn("generationConfig",body)
    def test_scientific_validator_unchanged_and_strict(self):
        s={"scenario_id":"synthetic",**probe.SYNTHETIC_SNAPSHOT};valid={"target_decision_id":"synthetic-d1",**{x:[] for x in dpc.CATEGORIES}};valid["validity_conditions"]=[{"proposition":"Synthetic switch alpha is enabled.","source_type":"observed","source_refs":["/system_pre_change_context/knowledge_before/0/statement"]}]
        dpc.validate_pauto(valid,s)
        mutations=(lambda x:x.pop("expectations"),lambda x:x.update(target_decision_id="bad"),lambda x:x["validity_conditions"][0].update(source_refs=["/bad"]),lambda x:x["validity_conditions"][0].update(proposition="paraphrase"),lambda x:x["validity_conditions"][0].update(source_type="inferred",source_refs=[]))
        for mutate in mutations:
            bad=copy.deepcopy(valid);mutate(bad)
            with self.assertRaises(dpc.CaptureValidationError):dpc.validate_pauto(bad,s)
        bad=copy.deepcopy(valid);bad["constraints"]=[{"proposition":"x","source_type":"inferred","source_refs":["/target_decision/statement"]} for _ in range(12)]
        with self.assertRaises(dpc.CaptureValidationError):dpc.validate_pauto(bad,s)
        bad=copy.deepcopy(valid);bad["constraints"]=[{"proposition":"x","source_type":"inferred","source_refs":["/target_decision/statement"]*7}]
        with self.assertRaises(dpc.CaptureValidationError):dpc.validate_pauto(bad,s)
    def test_first_accepted_stops_and_budget_is_bounded(self):
        payload=json.dumps({"target_decision_id":"synthetic-d1",**{x:[] for x in dpc.CATEGORIES}});a=Adapter([StatusError(400),payload,"unused"])
        with patch.object(probe,"_git",return_value="commit"):summary=probe.run_probe(self.out,adapter_factory=lambda:a,sleep_fn=lambda _:None)
        self.assertEqual(summary["selected_first_accepted_variant"],"V1");self.assertEqual(summary["variants_attempted"],["V0","V1"]);self.assertEqual(a.calls,2);self.assertLessEqual(summary["live_provider_invocations"],4)
        outcomes=[json.loads(x) for x in (self.out/"probe_outcomes.jsonl").read_text().splitlines()];self.assertFalse(outcomes[0]["model_response_obtained"]);self.assertTrue(outcomes[1]["model_response_obtained"])
    def test_probe_is_synthetic_non_scientific_and_nonreusable(self):
        self.assertNotIn("dev-",probe.SYNTHETIC_PROMPT.lower());self.assertNotIn("dr-bench",probe.SYNTHETIC_PROMPT.lower())
        with patch.object(dpc,"load_scenarios",side_effect=AssertionError("DEV access")),patch.object(probe,"_git",return_value="commit"):
            a=Adapter([json.dumps({"target_decision_id":"synthetic-d1",**{x:[] for x in dpc.CATEGORIES}})]);summary=probe.run_probe(self.out,adapter_factory=lambda:a,sleep_fn=lambda _:None)
        manifest=json.loads((self.out/"probe_manifest.json").read_text());self.assertFalse(manifest["scientific_observation"]);self.assertFalse(manifest["benchmark_evaluation_authorized"]);self.assertFalse(manifest["artifact_reuse_for_science"]);self.assertFalse(summary["artifact_reuse_for_science"])
        with self.assertRaises(dpc.DecisionPremiseCaptureError):dpc._validate_pre_execute(self.out,dpc.SANITY_MANIFEST,dpc.SANITY_VERSION)
    def test_pgen_protocol_transport_and_historical_sanity_unchanged(self):
        self.assertEqual(dpc.protocol_sha256(),dpc.PROTOCOL_SHA256);self.assertEqual(dpc._schema_sha(dpc.PGEN_SCHEMA),"0c867c1bf4d2e63e739a807d473877193a66a6d77f64a486c2e8f26d8a3c5c3d");self.assertEqual(probe.run_delivery_attempts.__module__,"dr_baselines.dev_experiment");self.assertNotIn(400,dpc._transport()["retryable_statuses"]);self.assertNotIn(499,dpc._transport()["retryable_statuses"])
        historical=Path("decision-premise-capture-v01-sanity-output-v2");self.assertEqual(json.loads((historical/"capture_summary.json").read_text())["status"],"INCOMPLETE")

if __name__=="__main__":unittest.main()
