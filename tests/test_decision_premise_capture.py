import copy, json, shutil, tempfile, unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import dr_bench.catalog as catalog
import dr_baselines.decision_premise_capture as dpc
from dr_baselines.models import ModelResponse

class HoldoutGuard:
    def __init__(self,r,a):self.r,self.a=r,a
    def joinpath(self,*parts):
        if any(str(x).replace("\\","/").endswith("holdout.jsonl") for x in parts):self.a.append(parts);raise AssertionError("holdout access")
        return HoldoutGuard(self.r.joinpath(*parts),self.a)
    def read_text(self,*a,**k):return self.r.read_text(*a,**k)

class Adapter:
    identifier="offline-mock"
    def __init__(self,responses):self.responses=list(responses);self.calls=0;self.schemas=[]
    def generate(self,*a,**k):self.calls+=1;v=self.responses.pop(0);return v if isinstance(v,ModelResponse) else ModelResponse(text=v)
    def close(self):pass

class DecisionPremiseCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.scenarios=catalog.load_scenarios("dev");cls.snapshots=dpc.build_snapshots(cls.scenarios)
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.out=Path(self.t.name)/"out"
    def git(self):return patch.object(dpc,"_git",side_effect=lambda *a:dpc.PASSED_SANITY_IMPLEMENTATION_SHA if a[:2]==("rev-parse","HEAD") else "")
    def passed_sanity(self):
        sanity=Path(self.t.name)/"sanity"
        with self.git():dpc.prepare_sanity(sanity)
        plan=json.loads((sanity/"execution_plan.json").read_text());snaps=json.loads((sanity/"snapshots.json").read_text());sm={(x["scenario_id"],x["target_decision"]["id"]):x for x in snaps}
        runs=[]
        for x in plan:
            snap=sm[(x["scenario_id"],x["decision_id"])];payload={"target_decision_id":x["decision_id"],"grounded_items":[]} if x["condition_id"]=="PGEN" else {"target_decision_id":x["decision_id"],**{c:[] for c in dpc.CATEGORIES}};canonical,_=(dpc.validate_pgen(payload,snap) if x["condition_id"]=="PGEN" else dpc.validate_pauto(payload,snap));runs.append({**x,"validation_status":"valid","raw_model_response":dpc._compact(payload),"provider_error":None,"canonical_payload":canonical,"payload_sha256":dpc._sha(dpc._canonical(canonical))})
        (sanity/"capture_runs.jsonl").write_text("".join(json.dumps(x)+"\n" for x in runs))
        (sanity/"capture_summary.json").write_text(json.dumps({"experiment_version":dpc.SANITY_VERSION,"status":"PASS","planned":4,"terminal":4,"model_responses":4,"valid":4,"invalid":0,"provider_failures":0,"aborted":False,"downstream_eligible":False}))
        return sanity
    def test_snapshot_contract_all_36_timing_exclusions_and_hashes(self):
        snaps,proof=dpc.audit_snapshots();self.assertEqual(len(snaps),36);self.assertEqual(proof["pass_count"],36);self.assertTrue(proof["all_pass"])
        by={x["id"]:x for x in self.scenarios}
        for s,p in zip(snaps,proof["snapshot_proofs"]):
            raw=by[s["scenario_id"]];made=s["target_decision"]["made_at"]
            self.assertEqual(set(dpc.visible_snapshot(s)),{"system_pre_change_context","strictly_earlier_recorded_transmissions","strictly_earlier_system_recorded_decisions","target_decision"})
            self.assertNotIn("scenario_id",json.loads(dpc._capture_prompt("PGEN",s).split("\n\nCONSERVATIVE PRE-CHANGE SNAPSHOT:\n",1)[1]))
            self.assertEqual(s["system_pre_change_context"]["knowledge_before"],raw["candidate"]["knowledge_before"])
            self.assertTrue(all(x["at"]<made for x in s["strictly_earlier_recorded_transmissions"]));self.assertTrue(all(x["made_at"]<made for x in s["strictly_earlier_system_recorded_decisions"]));self.assertFalse(dpc._scan_keys(s));self.assertEqual(p["snapshot_sha256"],dpc._sha(dpc._canonical(dpc.visible_snapshot(s))))
    def test_dev_only_loader_and_holdout_guard(self):
        attempts=[];real=catalog.files
        with patch("dr_bench.catalog.files",side_effect=lambda pkg:HoldoutGuard(real(pkg),attempts)),patch.object(dpc,"load_scenarios",wraps=catalog.load_scenarios) as loader:dpc.audit_snapshots()
        self.assertEqual(attempts,[]);self.assertTrue(all(x.args==("dev",) for x in loader.call_args_list))
    def test_pgen_exact_grounding_schema_caps_duplicates_and_target(self):
        s=self.snapshots[0];valid={"target_decision_id":s["target_decision"]["id"],"grounded_items":[{"source_path":"/target_decision/statement","source_text":s["target_decision"]["statement"]}]};canon,diag=dpc.validate_pgen(valid,s);self.assertEqual(diag["item_count"],1);self.assertEqual(set(dpc.PGEN_SCHEMA["properties"]),{"target_decision_id","grounded_items"})
        for mutate in (lambda v:v["grounded_items"][0].update(source_text="substring"),lambda v:v["grounded_items"][0].update(source_path="/target_decision"),lambda v:v.update(target_decision_id="wrong"),lambda v:v["grounded_items"].append(copy.deepcopy(v["grounded_items"][0])),lambda v:v.update(extra=True)):
            bad=copy.deepcopy(valid);mutate(bad)
            with self.assertRaises(dpc.CaptureValidationError):dpc.validate_pgen(bad,s)
    def test_pauto_observed_inferred_categories_refs_caps_and_target(self):
        s=self.snapshots[0];base={"target_decision_id":s["target_decision"]["id"],**{x:[] for x in dpc.CATEGORIES}};base["validity_conditions"]=[{"proposition":s["target_decision"]["statement"],"source_type":"observed","source_refs":["/target_decision/statement"]}];base["expectations"]=[{"proposition":"An inferred expectation","source_type":"inferred","source_refs":["/target_decision/statement"]}]
        _,diag=dpc.validate_pauto(base,s);self.assertEqual((diag["observed_item_count"],diag["inferred_item_count"]),(1,1));self.assertEqual(set(dpc.PAUTO_SCHEMA["properties"]),{"target_decision_id",*dpc.CATEGORIES})
        for mutate in (lambda v:v["expectations"][0].update(source_type="elicited"),lambda v:v["expectations"][0].update(source_refs=[]),lambda v:v["validity_conditions"][0].update(proposition="paraphrase"),lambda v:v.update(target_decision_id="wrong"),lambda v:v.update(oracle=True)):
            bad=copy.deepcopy(base);mutate(bad)
            with self.assertRaises(dpc.CaptureValidationError):dpc.validate_pauto(bad,s)
        bad=copy.deepcopy(base);bad["constraints"]=[copy.deepcopy(base["expectations"][0]) for _ in range(11)]
        with self.assertRaises(dpc.CaptureValidationError):dpc.validate_pauto(bad,s)
    def test_sanity_selection_plan_and_prepare_zero_provider(self):
        s1,s2=dpc.select_sanity(self.snapshots);self.assertEqual((s1["scenario_id"],s1["target_decision"]["id"]),("dev-001","d1"));self.assertEqual((s2["scenario_id"],s2["target_decision"]["id"]),("dev-006","d3"));plan=dpc.sanity_plan(self.snapshots);self.assertEqual([(x["condition_id"]) for x in plan],["PGEN","PAUTO","PAUTO","PGEN"])
        with self.git(),patch.object(dpc,"_dev_adapter_factory",side_effect=AssertionError("provider")):m=dpc.prepare_sanity(self.out)
        self.assertEqual(m["planned_scientific_observations"],4);self.assertTrue(m["execute_eligible"]);self.assertFalse(m["downstream_present"])
    def test_full_plans_balance_isolation_and_common_base(self):
        cp=dpc.capture_plan(self.snapshots);dp=dpc.downstream_plan();dpc.validate_capture_plan(cp);dpc.validate_downstream_plan(dp)
        self.assertEqual(Counter(x["condition_id"] for x in cp),Counter(PGEN=36,PAUTO=36));self.assertEqual(sum(cp[i]["condition_id"]=="PGEN" for i in range(0,72,2)),18)
        self.assertEqual(Counter(x["condition_id"] for x in dp),Counter({x:12 for x in dpc.DOWNSTREAM_CONDITIONS}))
        for c in dpc.DOWNSTREAM_CONDITIONS:self.assertEqual(Counter(x["temporal_position"] for x in dp if x["condition_id"]==c),Counter({1:3,2:3,3:3,4:3}))
        proof=dpc.downstream_proof(self.scenarios);self.assertEqual(proof["pass_count"],12);self.assertEqual(proof["ignored_diff_paths"],[]);self.assertTrue(all("discovery_condition" not in dpc.normalized_base(s) for s in self.scenarios))
    def test_context_bundles_order_identity_and_oracle_assumptions_only(self):
        s=self.scenarios[0];order=[x["id"] for x in sorted(s["candidate"]["decisions"],key=lambda x:(x["made_at"],x["id"]))];art={}
        for c in ("PGEN","PAUTO"):
            for did in order:art[(s["id"],did,c)]={"target_decision_id":did,"grounded_items":[]} if c=="PGEN" else {"target_decision_id":did,**{x:[] for x in dpc.CATEGORIES}}
        self.assertEqual(dpc.context_bundle(s,"P0",art),{"decision_records":[]})
        for c in ("PGEN","PAUTO","PORACLE"):self.assertEqual([x["target_decision_id"] for x in dpc.context_bundle(s,c,art)["decision_records"]],order)
        oracle=dpc.context_bundle(s,"PORACLE",art)["decision_records"];self.assertTrue(all(set(x)=={"target_decision_id","premises"} for x in oracle));self.assertEqual(oracle,dpc.oracle_records(s));self.assertFalse(any("evidence_available" in x for x in oracle))
    def test_full_prepare_scaffold_and_phase_isolation(self):
        sanity=self.passed_sanity()
        with self.git():m=dpc.prepare_full(self.out,sanity)
        self.assertEqual((m["capture_slots"],m["downstream_slots"]),(72,48));self.assertFalse(m["downstream_eligible"]);self.assertEqual(m["manifest_type"],dpc.FULL_MANIFEST)
        self.assertFalse(m["sanity_authentication"]["artifacts_reused"]);self.assertEqual(m["sanity_authentication"]["implementation_commit_sha"],dpc.PASSED_SANITY_IMPLEMENTATION_SHA)
        with self.assertRaises(dpc.DecisionPremiseCaptureError):dpc._validate_pre_execute(self.out,dpc.SANITY_MANIFEST,dpc.SANITY_VERSION)
    def test_full_prepare_authenticates_exact_sanity_artifacts(self):
        base=self.passed_sanity()
        with self.git():evidence=dpc._require_passed_sanity(base)
        self.assertEqual((evidence["slot_count"],evidence["valid"],evidence["sealed_holdout_accesses"]),(4,4,0));self.assertFalse(evidence["artifact_reuse_authorized"])
        def mutate(name,fn):
            target=Path(self.t.name)/name;shutil.copytree(base,target);fn(target)
            with self.git(),self.assertRaises(dpc.DecisionPremiseCaptureError):dpc.prepare_full(Path(self.t.name)/(name+"-out"),target)
        mutate("wrong-plan",lambda p:(p/"execution_plan.json").write_bytes((p/"execution_plan.json").read_bytes()+b" "))
        def wrong_slot(p):
            rows=json.loads((p/"execution_plan.json").read_text());rows[0]["scenario_id"]="dev-002";(p/"execution_plan.json").write_bytes(dpc._canonical(rows));m=json.loads((p/"experiment_manifest.json").read_text());m["execution_plan_sha256"]=dpc._sha((p/"execution_plan.json").read_bytes());(p/"experiment_manifest.json").write_bytes(dpc._canonical(m))
        mutate("wrong-slot",wrong_slot)
        def bad_manifest(field,value):
            return lambda p:(lambda m:((m.__setitem__(field,value)),(p/"experiment_manifest.json").write_bytes(dpc._canonical(m))))(json.loads((p/"experiment_manifest.json").read_text()))
        for field,value in (("protocol_sha256","bad"),("implementation_commit_sha","bad"),("pauto_scientific_schema_sha256","bad"),("pauto_provider_schema_sha256","bad"),("pauto_provider_config_sha256","bad"),("pgen_schema_sha256","bad"),("pgen_prompt_sha256","bad")):
            mutate("bad-"+field,bad_manifest(field,value))
        mutate("bad-proof",lambda p:(p/"snapshot_proof.json").write_bytes((p/"snapshot_proof.json").read_bytes()+b" "))
        def bad_summary(p):
            s=json.loads((p/"capture_summary.json").read_text());s["provider_failures"]=1;s["status"]="INCOMPLETE";(p/"capture_summary.json").write_bytes(dpc._canonical(s))
        mutate("bad-summary",bad_summary)
    def _complete_capture_fixture(self):
        sanity=self.passed_sanity()
        with self.git():dpc.prepare_full(self.out,sanity)
        plan=json.loads((self.out/"execution_plan.json").read_text());snaps=json.loads((self.out/"snapshots.json").read_text());sm={(x["scenario_id"],x["target_decision"]["id"]):x for x in snaps};runs=[]
        for e in plan:
            payload={"target_decision_id":e["decision_id"],"grounded_items":[]} if e["condition_id"]=="PGEN" else {"target_decision_id":e["decision_id"],**{x:[] for x in dpc.CATEGORIES}}
            canonical,_=(dpc.validate_pgen(payload,sm[(e["scenario_id"],e["decision_id"])]) if e["condition_id"]=="PGEN" else dpc.validate_pauto(payload,sm[(e["scenario_id"],e["decision_id"])]))
            runs.append({**e,"canonical_payload":canonical,"payload_sha256":dpc._sha(dpc._canonical(canonical)),"validation_status":"valid","provider_error":None})
        (self.out/"capture_runs.jsonl").write_text("".join(dpc._compact(x)+"\n" for x in runs));(self.out/"capture_summary.json").write_bytes(dpc._canonical({"experiment_version":dpc.FULL_VERSION,"planned":72,"terminal":72,"model_responses":72,"valid":72,"invalid":0,"provider_failures":0,"aborted":False,"missing_expected_capture_slots":0,"unexpected_capture_slots":0,"duplicate_capture_slots":0,"all_canonical_artifact_hashes_verify":True,"status":"CAPTURE COMPLETE","downstream_eligible":True}));return runs
    def test_exact_capture_set_and_pre_adapter_downstream_gate(self):
        runs=self._complete_capture_fixture();self.assertEqual(len(dpc._capture_artifacts(self.out)),72);constructed=[]
        rows=copy.deepcopy(runs);rows[-1]["scenario_id"]="dev-999";(self.out/"capture_runs.jsonl").write_text("".join(dpc._compact(x)+"\n" for x in rows))
        with self.git(),self.assertRaises(dpc.DecisionPremiseCaptureError):dpc.execute_downstream(self.out,adapter_factory=lambda:constructed.append(True))
        self.assertEqual(constructed,[])
        (self.out/"capture_runs.jsonl").write_text("".join(dpc._compact(x)+"\n" for x in runs[:-1]))
        with self.assertRaises(dpc.DecisionPremiseCaptureError):dpc._capture_artifacts(self.out)
    def test_contrast_details_and_strength_is_secondary(self):
        rows=self.rows();c=dpc._contrast(rows["P0"],rows["PAUTO"]);self.assertIn("corrections",c);self.assertIn("regressions",c);self.assertTrue(c["dependency_strength_secondary_only"]);self.assertEqual(dpc.classify(self.rows(oracle=False))["status"],"NO CONTEMPORARY PREMISE ADVANTAGE")
    def test_execute_integrity_fails_before_adapter(self):
        with self.git():dpc.prepare_sanity(self.out)
        constructed=[]
        with patch.object(dpc,"protocol_sha256",return_value="wrong"),self.git(),self.assertRaises(dpc.DecisionPremiseCaptureError):dpc.execute_sanity(self.out,adapter_factory=lambda:constructed.append(True))
        self.assertEqual(constructed,[])
        plan=self.out/"execution_plan.json";plan.write_bytes(plan.read_bytes()+b" ")
        with self.git(),self.assertRaises(dpc.DecisionPremiseCaptureError):dpc.execute_sanity(self.out,adapter_factory=lambda:constructed.append(True))
        self.assertEqual(constructed,[])
    def test_sanity_invalid_continues_no_regeneration_and_not_pass(self):
        with self.git():dpc.prepare_sanity(self.out)
        s={ (x["scenario_id"],x["target_decision"]["id"]):x for x in self.snapshots};plan=json.loads((self.out/"execution_plan.json").read_text());responses=[]
        for i,e in enumerate(plan):
            snap=s[(e["scenario_id"],e["decision_id"])]
            if i==0:responses.append("{}")
            elif e["condition_id"]=="PGEN":responses.append(json.dumps({"target_decision_id":e["decision_id"],"grounded_items":[]}))
            else:responses.append(json.dumps({"target_decision_id":e["decision_id"],**{x:[] for x in dpc.CATEGORIES}}))
        a=Adapter(responses)
        with self.git():summary=dpc.execute_sanity(self.out,adapter_factory=lambda:a,sleep_fn=lambda _:None)
        self.assertEqual(a.calls,4);self.assertEqual(summary["invalid"],1);self.assertNotEqual(summary["status"],"PASS")
    def rows(self,pauto="all",pgen="none",oracle=True,regress=False,strength=False):
        rows={c:[] for c in dpc.DOWNSTREAM_CONDITIONS}
        for c in rows:
            for sid,did in (("x","d1"),("x","d2")):
                truth=True;pred=True
                if c=="P0" and did=="d1":pred=False
                if c=="PORACLE" and (not oracle) and did=="d1":pred=False
                if c=="PAUTO" and pauto=="none" and did=="d1":pred=False
                if c=="PAUTO" and pauto=="partial" and did=="d2":pred=False
                if c=="PGEN" and pgen=="none" and did=="d1":pred=False
                if c=="PAUTO" and regress and did=="d2":pred=False
                rows[c].append({"scenario_id":sid,"decision_id":did,"true_materially_dependent":truth,"predicted_materially_dependent":pred,"true_still_justified":True,"predicted_still_justified":True,"true_dependency_strength":"material","predicted_dependency_strength":"material" if not(strength and c=="P0") else "critical"})
        return rows
    def test_analysis_classification_categories_and_no_historical_substitution(self):
        self.assertEqual(dpc.classify(self.rows())["status"],"AUTO SUFFICIENT")
        self.assertEqual(dpc.classify(self.rows(pgen="all"))["status"],"AUTO GENERIC-EQUIVALENT")
        self.assertEqual(dpc.classify(self.rows(oracle=False))["status"],"NO CONTEMPORARY PREMISE ADVANTAGE")
        self.assertEqual(dpc.classify(self.rows(regress=True))["status"],"AUTO HARMFUL")
        self.assertIn(dpc.classify(self.rows(pauto="none",strength=True))["status"],{"AUTO STRUCTURAL-ONLY","AMBIGUOUS"})
    def test_transport_and_science_are_shared(self):
        self.assertEqual(dpc.run_delivery_attempts.__module__,"dr_baselines.dev_experiment");self.assertNotIn(499,dpc._transport()["retryable_statuses"]);self.assertEqual(dpc._sha(dpc.BASE_TASK_PROMPT.encode()),"2ed1e0280d3108aa9f7458bc7a21d4cf9f82ad2e6c4795d2ac516fffdb5557b1")

    def test_v1_provider_schema_is_distinct_exact_and_frozen_in_prepare(self):
        self.assertEqual(dpc._schema_sha(dpc.PAUTO_SCHEMA),dpc.PAUTO_SCIENTIFIC_SCHEMA_SHA256)
        provider=dpc.pauto_provider_schema();self.assertEqual(dpc._schema_sha(provider),dpc.PAUTO_PROVIDER_SCHEMA_SHA256);self.assertEqual(dpc.pauto_provider_config_sha256(),dpc.PAUTO_PROVIDER_CONFIG_SHA256)
        def paths(v,path=""):
            out=[]
            if isinstance(v,dict):
                for k,x in v.items():out.extend(paths(x,path+"/"+k))
            elif isinstance(v,list):
                for i,x in enumerate(v):out.extend(paths(x,path+f"/{i}"))
            return out+[path]
        self.assertFalse(any(x.endswith(("/minItems","/maxItems")) for x in paths(provider)))
        self.assertEqual(set(provider["properties"]),{"target_decision_id",*dpc.CATEGORIES});self.assertEqual(provider["properties"]["validity_conditions"]["items"]["properties"]["source_type"]["enum"],["observed","inferred"])
        with self.git():manifest=dpc.prepare_sanity(self.out)
        self.assertEqual(manifest["pauto_scientific_schema_sha256"],dpc.PAUTO_SCIENTIFIC_SCHEMA_SHA256);self.assertEqual(manifest["pauto_provider_schema_sha256"],dpc.PAUTO_PROVIDER_SCHEMA_SHA256);self.assertEqual(manifest["pauto_provider_config_sha256"],dpc.PAUTO_PROVIDER_CONFIG_SHA256)
        path=self.out/"experiment_manifest.json";mutated=json.loads(path.read_text());mutated["pauto_provider_schema_sha256"]="bad";path.write_bytes(dpc._canonical(mutated));constructed=[]
        with self.git(),self.assertRaises(dpc.DecisionPremiseCaptureError):dpc.execute_sanity(self.out,adapter_factory=lambda:constructed.append(True))
        self.assertEqual(constructed,[])

if __name__=="__main__":unittest.main()
