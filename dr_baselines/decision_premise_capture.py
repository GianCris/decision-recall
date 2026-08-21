"""Decision Premise Capture v0.1: DEV-only offline preparation and phased runner."""
from __future__ import annotations

import argparse, copy, hashlib, json, subprocess, sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Callable

from dr_bench import candidate_view, evaluate_discovery, load_scenarios
from .baselines import BASE_TASK_PROMPT
from .config import ExperimentConfig
from .dev_experiment import (DELIVERY_BACKOFF_SECONDS, DELIVERY_POLICY_VERSION, INTER_CALL_DELAY_SECONDS,
    LOCATION, MAX_DELIVERY_ATTEMPTS, MODEL_ID, PROJECT_ID, SDK_PACKAGE, SDK_VERSION, TRANSPORT_ATTEMPTS,
    TRANSPORT_TIMEOUT_MS, TRANSPORT_TIMEOUT_SECONDS, _dev_adapter_factory, run_delivery_attempts)
from .output import (DISCOVERY_RESPONSE_JSON_SCHEMA, DISCOVERY_RESPONSE_MIME_TYPE,
    DISCOVERY_RESPONSE_SCHEMA_VERSION, OutputValidationError, parse_discovery_response)
from .round_b import _condition_metrics
from .runner import with_structured_output_metadata

PROTOCOL_PATH=Path("docs/DECISION_PREMISE_CAPTURE_PROTOCOL_V0.1.md")
PROTOCOL_COMMIT="49991bf6bc9f9cbecb8bd981ccaacb1974bbd861"
PROTOCOL_SHA256="7beac6d4d9aa75dc83dbff5aa86bd4c8f942a6f9de89879eb12f707fb3c413cd"
SANITY_VERSION="decision-premise-capture-sanity-v0.1"; FULL_VERSION="decision-premise-capture-v0.1"
SANITY_MANIFEST="decision-premise-capture-sanity-manifest-v0.1"; FULL_MANIFEST="decision-premise-capture-manifest-v0.1"
DEV_IDS=tuple(f"dev-{i:03d}" for i in range(1,13)); CAPTURE_CONDITIONS=("PGEN","PAUTO")
DOWNSTREAM_CONDITIONS=("P0","PGEN","PAUTO","PORACLE"); CATEGORIES=("validity_conditions","independent_reasons","constraints","expectations")
MAX_CAPTURE_ITEMS_PER_DECISION=12; MAX_SOURCE_REFS_PER_ITEM=6
FORBIDDEN_SNAPSHOT_FIELDS={"brief","change","world","consequences","recovery_actions","evidence_available","assumptions","private","complexity","title","domain","split","discovery_condition","materially_dependent","still_justified","dependency_strength"}

PGEN_INSTRUCTION="""Select useful pre-change context extractively. Return only target_decision_id and grounded_items. Each source_path is an RFC 6901 pointer into the supplied snapshot and source_text must exactly equal the complete resolved string. Do not paraphrase, infer, rank, or judge premises, causality, materiality, sufficiency, dependency, or survivability."""
PAUTO_INSTRUCTION="""Capture decision premises from the supplied pre-change snapshot as validity_conditions, independent_reasons, constraints, and expectations. Each item has proposition, source_type (observed or inferred), and source_refs using RFC 6901 pointers. Observed text must exactly equal its single terminal-string source. Inferred text needs at least one visible source reference and is not a verified fact. Do not use future, private, oracle, or post-change information."""
PGEN_SCHEMA={"type":"object","additionalProperties":False,"required":["target_decision_id","grounded_items"],"properties":{"target_decision_id":{"type":"string"},"grounded_items":{"type":"array","maxItems":12,"items":{"type":"object","additionalProperties":False,"required":["source_path","source_text"],"properties":{"source_path":{"type":"string"},"source_text":{"type":"string"}}}}}}
_ITEM_SCHEMA={"type":"object","additionalProperties":False,"required":["proposition","source_type","source_refs"],"properties":{"proposition":{"type":"string"},"source_type":{"type":"string","enum":["observed","inferred"]},"source_refs":{"type":"array","minItems":1,"maxItems":6,"items":{"type":"string"}}}}
PAUTO_SCHEMA={"type":"object","additionalProperties":False,"required":["target_decision_id",*CATEGORIES],"properties":{"target_decision_id":{"type":"string"},**{x:{"type":"array","maxItems":12,"items":_ITEM_SCHEMA} for x in CATEGORIES}}}
PAUTO_SCIENTIFIC_SCHEMA_SHA256="4ab0c659fb4932fdd342518271661b440dd3f42e553c2307e947929de93ef5f3"
PAUTO_PROVIDER_SCHEMA_SHA256="028c6826f305622741e8c18d60b0c8b4d81ac76c7c208f4844fbdf96a811529f"
PAUTO_PROVIDER_CONFIG_SHA256="9d851e44e4ed7292771ec459820f037fc226e31daf09771e9afcd6b2a2b6d981"

class DecisionPremiseCaptureError(RuntimeError): pass
class CaptureValidationError(ValueError): pass
def _canonical(v:Any)->bytes:return (json.dumps(v,sort_keys=True,indent=2,ensure_ascii=False)+"\n").encode()
def _compact(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def _schema_sha(v:dict)->str:return _sha(_compact(v).encode())
def _git(*a:str)->str:return subprocess.run(["git",*a],check=True,capture_output=True,text=True).stdout.strip()
def _now()->str:return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def protocol_sha256()->str:return _sha(PROTOCOL_PATH.read_bytes())
def _remove_provider_item_limits(value:Any)->Any:
    if isinstance(value,dict):return {key:_remove_provider_item_limits(item) for key,item in value.items() if key not in {"minItems","maxItems"}}
    if isinstance(value,list):return [_remove_provider_item_limits(item) for item in value]
    return copy.deepcopy(value)
def pauto_provider_schema()->dict:
    schema=_remove_provider_item_limits(PAUTO_SCHEMA)
    if _schema_sha(PAUTO_SCHEMA)!=PAUTO_SCIENTIFIC_SCHEMA_SHA256 or _schema_sha(schema)!=PAUTO_PROVIDER_SCHEMA_SHA256:raise DecisionPremiseCaptureError("frozen PAUTO scientific/provider schema identity mismatch")
    return schema
def pauto_provider_config_sha256()->str:
    value={"response_mime_type":"application/json","schema_input_path":"response_json_schema","schema":pauto_provider_schema()}
    digest=_sha(_canonical(value))
    if digest!=PAUTO_PROVIDER_CONFIG_SHA256:raise DecisionPremiseCaptureError("frozen PAUTO provider config identity mismatch")
    return digest
def _dev()->list[dict]:
    s=load_scenarios("dev")
    if tuple(x["id"] for x in s)!=DEV_IDS:raise DecisionPremiseCaptureError("DEV inventory mismatch")
    return s

def _public_decision(d:dict)->dict:return {k:copy.deepcopy(d[k]) for k in ("id","agent_id","made_at","statement")}
def build_snapshot(scenario:dict,target:dict)->dict:
    made=target["made_at"]
    return {"scenario_id":scenario["id"],"system_pre_change_context":{"agents":copy.deepcopy(scenario["candidate"]["agents"]),"knowledge_before":copy.deepcopy(scenario["candidate"]["knowledge_before"])},
        "strictly_earlier_recorded_transmissions":[copy.deepcopy(x) for x in scenario["candidate"]["transmissions"] if x["at"]<made],
        "strictly_earlier_system_recorded_decisions":[_public_decision(x) for x in scenario["candidate"]["decisions"] if x["made_at"]<made],"target_decision":_public_decision(target)}
def visible_snapshot(snapshot:dict)->dict:
    return {k:copy.deepcopy(snapshot[k]) for k in ("system_pre_change_context","strictly_earlier_recorded_transmissions","strictly_earlier_system_recorded_decisions","target_decision")}
def build_snapshots(scenarios:list[dict]|None=None)->list[dict]:
    scenarios=_dev() if scenarios is None else scenarios
    return [build_snapshot(s,d) for s in scenarios for d in sorted(s["candidate"]["decisions"],key=lambda x:x["id"])]
def _scan_keys(v:Any)->set[str]:
    if isinstance(v,dict):return set(v)&FORBIDDEN_SNAPSHOT_FIELDS | set().union(*(_scan_keys(x) for x in v.values()),set())
    if isinstance(v,list):return set().union(*(_scan_keys(x) for x in v),set())
    return set()
def snapshot_proof(scenario:dict,snapshot:dict)->dict:
    target=snapshot["target_decision"]; made=target["made_at"]; tx=scenario["candidate"]["transmissions"]; ds=scenario["candidate"]["decisions"]
    forbidden=sorted(_scan_keys(snapshot)); ok=not forbidden and all(x["at"]<made for x in snapshot["strictly_earlier_recorded_transmissions"]) and all(x["made_at"]<made for x in snapshot["strictly_earlier_system_recorded_decisions"])
    return {"scenario_id":scenario["id"],"target_decision_id":target["id"],"target_agent_id":target["agent_id"],"target_made_at":made,"snapshot_sha256":_sha(_canonical(visible_snapshot(snapshot))),
      "included_knowledge_ids":[x["id"] for x in snapshot["system_pre_change_context"]["knowledge_before"]],"included_transmission_ids":[x["id"] for x in tx if x["at"]<made],"included_prior_decision_ids":[x["id"] for x in ds if x["made_at"]<made],
      "excluded_same_time_transmission_ids":[x["id"] for x in tx if x["at"]==made],"excluded_future_transmission_ids":[x["id"] for x in tx if x["at"]>made],"excluded_later_decision_ids":[x["id"] for x in ds if x["made_at"]>=made and x["id"]!=target["id"]],
      "forbidden_fields_found":forbidden,"dev_only_loader":True,"pass":ok}
def audit_snapshots()->tuple[list[dict],dict]:
    scenarios=_dev(); by={x["id"]:x for x in scenarios}; snaps=build_snapshots(scenarios); proofs=[snapshot_proof(by[x["scenario_id"]],x) for x in snaps]
    payload={"proof_version":"conservative-pre-change-snapshot-proof-v0.1","snapshot_count":len(snaps),"pass_count":sum(x["pass"] for x in proofs),"forbidden_violation_count":sum(bool(x["forbidden_fields_found"]) for x in proofs),"dev_only":True,"all_pass":len(snaps)==36 and all(x["pass"] for x in proofs),"snapshot_proofs":proofs}
    return snaps,payload

def resolve_pointer(root:dict,pointer:str)->Any:
    if not isinstance(pointer,str) or not pointer.startswith("/"):raise CaptureValidationError("invalid RFC 6901 pointer")
    cur:Any=root
    for raw in pointer.split("/")[1:]:
        if "~" in raw.replace("~0","").replace("~1",""):raise CaptureValidationError("invalid RFC 6901 escape")
        token=raw.replace("~1","/").replace("~0","~")
        if isinstance(cur,dict) and token in cur:cur=cur[token]
        elif isinstance(cur,list) and token.isdigit() and (token=="0" or not token.startswith("0")) and int(token)<len(cur):cur=cur[int(token)]
        else:raise CaptureValidationError("source reference does not resolve")
    return cur
def _keys(v:Any,expected:set[str],label:str):
    if not isinstance(v,dict) or set(v)!=expected:raise CaptureValidationError(label+" invalid fields")
def validate_pgen(v:Any,snapshot:dict)->tuple[dict,dict]:
    snapshot=visible_snapshot(snapshot)
    _keys(v,{"target_decision_id","grounded_items"},"PGEN")
    if v["target_decision_id"]!=snapshot["target_decision"]["id"]:raise CaptureValidationError("target_decision_id mismatch")
    items=v["grounded_items"]
    if not isinstance(items,list) or len(items)>12:raise CaptureValidationError("grounded_items capacity")
    paths=[]
    for item in items:
        _keys(item,{"source_path","source_text"},"grounded item"); resolved=resolve_pointer(snapshot,item["source_path"])
        if not isinstance(resolved,str) or item["source_text"]!=resolved:raise CaptureValidationError("grounding must equal complete terminal string")
        paths.append(item["source_path"])
    if len(paths)!=len(set(paths)):raise CaptureValidationError("duplicate source path")
    canonical={"target_decision_id":v["target_decision_id"],"grounded_items":sorted(copy.deepcopy(items),key=lambda x:x["source_path"])}
    return canonical,{"item_count":len(items),"invalid_refs":0,"extraction_valid":True}
def validate_pauto(v:Any,snapshot:dict)->tuple[dict,dict]:
    snapshot=visible_snapshot(snapshot)
    _keys(v,{"target_decision_id",*CATEGORIES},"PAUTO")
    if v["target_decision_id"]!=snapshot["target_decision"]["id"]:raise CaptureValidationError("target_decision_id mismatch")
    total=observed=inferred=0; canonical={"target_decision_id":v["target_decision_id"]}; counts={}
    for category in CATEGORIES:
        if not isinstance(v[category],list):raise CaptureValidationError(category+" must be array")
        out=[]; counts[category]=len(v[category]); total+=len(v[category])
        for item in v[category]:
            _keys(item,{"proposition","source_type","source_refs"},"premise item")
            if item["source_type"] not in {"observed","inferred"}:raise CaptureValidationError("invalid source_type")
            refs=item["source_refs"]
            if not isinstance(refs,list) or not refs or len(refs)>6 or len(refs)!=len(set(refs)):raise CaptureValidationError("invalid source_refs")
            resolved=[resolve_pointer(snapshot,x) for x in refs]
            if item["source_type"]=="observed":
                observed+=1
                if len(refs)!=1 or not isinstance(resolved[0],str) or item["proposition"]!=resolved[0]:raise CaptureValidationError("observed proposition must equal one terminal string")
            else: inferred+=1
            if not isinstance(item["proposition"],str) or not item["proposition"]:raise CaptureValidationError("empty proposition")
            out.append(copy.deepcopy(item))
        canonical[category]=sorted(out,key=lambda x:(x["source_type"],x["proposition"],x["source_refs"]))
    if total>12:raise CaptureValidationError("PAUTO total capacity")
    return canonical,{"observed_item_count":observed,"inferred_item_count":inferred,"invalid_source_ref_count":0,"unreferenced_inference_count":0,"items_by_category":counts}

def select_sanity(snaps:list[dict])->tuple[dict,dict]:
    ordered=sorted(snaps,key=lambda x:(x["scenario_id"],x["target_decision"]["id"])); s1=ordered[0]
    score=lambda x:len(x["system_pre_change_context"]["knowledge_before"])+len(x["strictly_earlier_recorded_transmissions"])+len(x["strictly_earlier_system_recorded_decisions"])
    s2=sorted(ordered[1:],key=lambda x:(-score(x),x["scenario_id"],x["target_decision"]["id"]))[0]; return s1,s2
def sanity_plan(snaps:list[dict])->list[dict]:
    a,b=select_sanity(snaps); pairs=((a,"PGEN"),(a,"PAUTO"),(b,"PAUTO"),(b,"PGEN"))
    return [{"global_execution_index":i,"scenario_id":s["scenario_id"],"decision_id":s["target_decision"]["id"],"condition_id":c,"observation_kind":"capture","snapshot_sha256":_sha(_canonical(visible_snapshot(s)))} for i,(s,c) in enumerate(pairs,1)]
def capture_plan(snaps:list[dict])->list[dict]:
    out=[]
    for n,s in enumerate(sorted(snaps,key=lambda x:(x["scenario_id"],x["target_decision"]["id"])),1):
        order=("PGEN","PAUTO") if n%2 else ("PAUTO","PGEN")
        for c in order:out.append({"global_execution_index":len(out)+1,"snapshot_index":n,"scenario_id":s["scenario_id"],"decision_id":s["target_decision"]["id"],"condition_id":c,"observation_kind":"capture","snapshot_sha256":_sha(_canonical(visible_snapshot(s)))})
    return out
def downstream_plan()->list[dict]:
    rows=(("P0","PGEN","PAUTO","PORACLE"),("PGEN","PAUTO","PORACLE","P0"),("PAUTO","PORACLE","P0","PGEN"),("PORACLE","P0","PGEN","PAUTO")); out=[]
    for n,sid in enumerate(DEV_IDS):
        for pos,c in enumerate(rows[n%4],1):out.append({"global_execution_index":len(out)+1,"scenario_id":sid,"repetition_id":"1","condition_id":c,"temporal_position":pos,"observation_kind":"final"})
    return out
def validate_sanity_plan(p:list[dict]):
    if len(p)!=4 or Counter(x["condition_id"] for x in p)!=Counter({"PGEN":2,"PAUTO":2}):raise DecisionPremiseCaptureError("invalid sanity plan")
def validate_capture_plan(p:list[dict]):
    if len(p)!=72 or Counter(x["condition_id"] for x in p)!=Counter({"PGEN":36,"PAUTO":36}):raise DecisionPremiseCaptureError("invalid capture plan")
    if sum(p[i]["condition_id"]=="PGEN" for i in range(0,72,2))!=18:raise DecisionPremiseCaptureError("capture first-order imbalance")
def validate_downstream_plan(p:list[dict]):
    if len(p)!=48 or Counter(x["condition_id"] for x in p)!=Counter({x:12 for x in DOWNSTREAM_CONDITIONS}):raise DecisionPremiseCaptureError("invalid downstream plan")
    for c in DOWNSTREAM_CONDITIONS:
        if Counter(x["temporal_position"] for x in p if x["condition_id"]==c)!=Counter({1:3,2:3,3:3,4:3}):raise DecisionPremiseCaptureError("downstream temporal imbalance")

def normalized_base(s:dict)->dict:
    v=candidate_view(s,"discovery","implicit"); v.pop("discovery_condition"); return v
def oracle_records(s:dict)->list[dict]:
    return [{"target_decision_id":d["id"],"premises":copy.deepcopy(d["assumptions"])} for d in sorted(s["candidate"]["decisions"],key=lambda d:(d["made_at"],d["id"]))]
def downstream_proof(scenarios:list[dict])->dict:
    proofs=[]
    for s in scenarios:
        base=normalized_base(s); order=[d["id"] for d in sorted(s["candidate"]["decisions"],key=lambda d:(d["made_at"],d["id"]))]
        proofs.append({"scenario_id":s["id"],"normalized_base_sha256":_sha(_canonical(base)),"discovery_condition_absent":"discovery_condition" not in base,"ignored_diff_paths":[],"canonical_decision_order":order,"poracle_decision_order":[x["target_decision_id"] for x in oracle_records(s)],"pass":"discovery_condition" not in base and order==[x["target_decision_id"] for x in oracle_records(s)]})
    return {"proof_version":"downstream-common-base-v0.1","scenario_proofs":proofs,"pass_count":sum(x["pass"] for x in proofs),"all_pass":all(x["pass"] for x in proofs),"ignored_diff_paths":[]}

def _config(version:str)->ExperimentConfig:return with_structured_output_metadata(ExperimentConfig(version=version,model_name=MODEL_ID,repetitions=1,dataset_id="DR-Bench",dataset_version="0.1",scenario_ids=DEV_IDS,candidate_view_contract_version="0.1",generation_config=(("delivery_policy_version",DELIVERY_POLICY_VERSION),)),True)
def _transport()->dict:return {"sdk_attempts":TRANSPORT_ATTEMPTS,"max_delivery_attempts":MAX_DELIVERY_ATTEMPTS,"retryable_statuses":[408,429,500,502,503,504],"backoff_seconds":list(DELIVERY_BACKOFF_SECONDS),"jitter":False,"timeout_ms":TRANSPORT_TIMEOUT_MS,"timeout_seconds":TRANSPORT_TIMEOUT_SECONDS,"inter_slot_seconds":INTER_CALL_DELAY_SECONDS,"concurrency":1,"first_model_response_wins":True}
def _manifest_common(version:str,mtype:str,plan:bytes,proof:bytes)->dict:return {"experiment_version":version,"manifest_type":mtype,"protocol_commit_sha":PROTOCOL_COMMIT,"protocol_sha256":PROTOCOL_SHA256,"implementation_commit_sha":_git("rev-parse","HEAD"),"created_at_utc":_now(),"execution_plan_sha256":_sha(plan),"snapshot_proof_sha256":_sha(proof),"pgen_prompt_sha256":_sha(PGEN_INSTRUCTION.encode()),"pauto_prompt_sha256":_sha(PAUTO_INSTRUCTION.encode()),"pgen_schema_sha256":_schema_sha(PGEN_SCHEMA),"pauto_scientific_schema_sha256":_schema_sha(PAUTO_SCHEMA),"pauto_provider_schema_sha256":_schema_sha(pauto_provider_schema()),"pauto_provider_config_sha256":pauto_provider_config_sha256(),"pauto_provider_schema_compatibility":"validated V1: scientific schema minus provider-side minItems/maxItems only","discovery_prompt_sha256":_sha(BASE_TASK_PROMPT.encode()),"discovery_schema_sha256":_schema_sha(DISCOVERY_RESPONSE_JSON_SCHEMA),"model_id":MODEL_ID,"provider":"Google Cloud Agent Platform / Vertex","project_id":PROJECT_ID,"location":LOCATION,"sdk_package":SDK_PACKAGE,"sdk_version":SDK_VERSION,"experiment_config":_config(version).to_dict(),"transport":_transport(),"fresh_calls_required":True,"historical_response_reuse_authorized":False,"sealed_holdout_excluded":True}
def _prepare_common(out:Path,full:bool)->dict:
    if out.exists():raise DecisionPremiseCaptureError("output directory already exists")
    if protocol_sha256()!=PROTOCOL_SHA256:raise DecisionPremiseCaptureError("protocol SHA mismatch")
    if _git("status","--porcelain","--untracked-files=no"):raise DecisionPremiseCaptureError("tracked worktree must be clean")
    snaps,proof=audit_snapshots(); plan=capture_plan(snaps) if full else sanity_plan(snaps); validate_capture_plan(plan) if full else validate_sanity_plan(plan)
    proof_bytes=_canonical(proof); plan_bytes=_canonical(plan); version=FULL_VERSION if full else SANITY_VERSION; mtype=FULL_MANIFEST if full else SANITY_MANIFEST
    manifest=_manifest_common(version,mtype,plan_bytes,proof_bytes); manifest.update({"prepare_status":"PREPARED" if proof["all_pass"] else "BLOCKED","execute_eligible":proof["all_pass"],"snapshot_count":36,"snapshot_pass_count":proof["pass_count"],"sanity_artifact_reuse_forbidden":True})
    if full:
        dp=downstream_plan(); validate_downstream_plan(dp); sp=downstream_proof(_dev()); dpb=_canonical(dp); spb=_canonical(sp)
        manifest.update({"capture_slots":72,"downstream_slots":48,"downstream_plan_sha256":_sha(dpb),"downstream_proof_sha256":_sha(spb),"downstream_eligible":False,"analysis_version":"decision-premise-capture-analysis-v0.1"})
    else:
        s1,s2=select_sanity(snaps); manifest.update({"planned_scientific_observations":4,"s1":{"scenario_id":s1["scenario_id"],"decision_id":s1["target_decision"]["id"]},"s2":{"scenario_id":s2["scenario_id"],"decision_id":s2["target_decision"]["id"]},"pass_rule":"4/4 terminal model responses valid; zero provider failures; no abort","downstream_present":False})
    out.mkdir(); (out/"execution_plan.json").write_bytes(plan_bytes); (out/"snapshot_proof.json").write_bytes(proof_bytes); (out/"snapshots.json").write_bytes(_canonical(snaps))
    if full:(out/"downstream_plan.json").write_bytes(dpb); (out/"downstream_structural_proof.json").write_bytes(spb)
    (out/"experiment_manifest.json").write_bytes(_canonical(manifest)); return manifest
def prepare_sanity(out:Path)->dict:return _prepare_common(out,False)
def _require_passed_sanity(sanity_dir:Path)->None:
    mp=sanity_dir/"experiment_manifest.json"; sp=sanity_dir/"capture_summary.json"; rp=sanity_dir/"capture_runs.jsonl"
    if not all(x.exists() for x in (mp,sp,rp)):raise DecisionPremiseCaptureError("separately passed sanity evidence required")
    manifest=json.loads(mp.read_text()); summary=json.loads(sp.read_text()); runs=[json.loads(x) for x in rp.read_text().splitlines() if x]
    if manifest.get("manifest_type")!=SANITY_MANIFEST or manifest.get("experiment_version")!=SANITY_VERSION or summary.get("status")!="PASS" or summary.get("planned")!=4 or summary.get("terminal")!=4 or summary.get("model_responses")!=4 or summary.get("valid")!=4 or summary.get("invalid") or summary.get("provider_failures") or summary.get("aborted") or len(runs)!=4 or any(x.get("validation_status")!="valid" for x in runs):raise DecisionPremiseCaptureError("sanity did not satisfy frozen 4/4 PASS gate")
def prepare_full(out:Path,sanity_dir:Path)->dict:
    _require_passed_sanity(sanity_dir)
    manifest=_prepare_common(out,True);manifest["sanity_gate"]={"source_directory":str(sanity_dir),"status":"PASS","artifacts_reused":False};(out/"experiment_manifest.json").write_bytes(_canonical(manifest));return manifest

def _validate_pre_execute(out:Path,mtype:str,version:str,plan_name="execution_plan.json",runtime_integrity:bool=True)->tuple[dict,list,dict]:
    mp=out/"experiment_manifest.json"; pp=out/plan_name; proofp=out/"snapshot_proof.json"
    if not all(x.exists() for x in (mp,pp,proofp)):raise DecisionPremiseCaptureError("prepared artifacts required")
    m=json.loads(mp.read_text()); pb=pp.read_bytes(); proofb=proofp.read_bytes(); plan=json.loads(pb); proof=json.loads(proofb)
    if m.get("manifest_type")!=mtype or m.get("experiment_version")!=version or m.get("protocol_commit_sha")!=PROTOCOL_COMMIT or m.get("protocol_sha256")!=PROTOCOL_SHA256:raise DecisionPremiseCaptureError("incompatible lifecycle manifest")
    if runtime_integrity:
        if protocol_sha256()!=m.get("protocol_sha256") or protocol_sha256()!=PROTOCOL_SHA256:raise DecisionPremiseCaptureError("protocol drift")
        if _git("rev-parse","HEAD")!=m.get("implementation_commit_sha") or _git("status","--porcelain","--untracked-files=no"):raise DecisionPremiseCaptureError("implementation/worktree drift")
    expected=m["downstream_plan_sha256"] if plan_name=="downstream_plan.json" else m["execution_plan_sha256"]
    if _sha(pb)!=expected or _sha(proofb)!=m["snapshot_proof_sha256"]:raise DecisionPremiseCaptureError("plan/proof byte identity mismatch")
    if not proof.get("all_pass") or proof.get("pass_count")!=36 or proof.get("forbidden_violation_count")!=0 or len(proof.get("snapshot_proofs",[]))!=36 or not all(x.get("pass") for x in proof["snapshot_proofs"]):raise DecisionPremiseCaptureError("snapshot proof failed")
    if m.get("pgen_prompt_sha256")!=_sha(PGEN_INSTRUCTION.encode()) or m.get("pauto_prompt_sha256")!=_sha(PAUTO_INSTRUCTION.encode()) or m.get("pgen_schema_sha256")!=_schema_sha(PGEN_SCHEMA) or m.get("pauto_scientific_schema_sha256")!=_schema_sha(PAUTO_SCHEMA) or m.get("pauto_provider_schema_sha256")!=_schema_sha(pauto_provider_schema()) or m.get("pauto_provider_config_sha256")!=pauto_provider_config_sha256():raise DecisionPremiseCaptureError("capture prompt/scientific/provider schema drift")
    if m.get("model_id")!=MODEL_ID or m.get("provider")!="Google Cloud Agent Platform / Vertex" or m.get("project_id")!=PROJECT_ID or m.get("location")!=LOCATION or m.get("transport")!=_transport() or _compact(m.get("experiment_config"))!=_compact(_config(version).to_dict()) or m.get("execute_eligible") is not True:raise DecisionPremiseCaptureError("model/config/eligibility mismatch")
    if plan_name=="downstream_plan.json":
        sp=out/"downstream_structural_proof.json"
        if not sp.exists() or _sha(sp.read_bytes())!=m.get("downstream_proof_sha256"):raise DecisionPremiseCaptureError("downstream structural-proof identity mismatch")
        structure=json.loads(sp.read_text())
        if structure.get("all_pass") is not True or structure.get("pass_count")!=12 or structure.get("ignored_diff_paths")!=[] or len(structure.get("scenario_proofs",[]))!=12 or not all(x.get("pass") and x.get("discovery_condition_absent") and x.get("ignored_diff_paths")==[] for x in structure["scenario_proofs"]):raise DecisionPremiseCaptureError("downstream structural proof failed")
    (validate_downstream_plan(plan) if plan_name=="downstream_plan.json" else validate_capture_plan(plan) if version==FULL_VERSION else validate_sanity_plan(plan)); return m,plan,json.loads((out/"snapshots.json").read_text())
def _capture_prompt(c:str,s:dict)->str:return (PGEN_INSTRUCTION if c=="PGEN" else PAUTO_INSTRUCTION)+"\n\nCONSERVATIVE PRE-CHANGE SNAPSHOT:\n"+_compact(visible_snapshot(s))
def _append(path:Path,v:dict):
    with path.open("a",encoding="utf-8",newline="\n") as f:f.write(_compact(v)+"\n")
def _execute_capture(out:Path,sanity:bool,adapter_factory:Callable[[],Any]=_dev_adapter_factory,sleep_fn:Callable[[float],None]=sleep)->dict:
    m,plan,snaps=_validate_pre_execute(out,SANITY_MANIFEST if sanity else FULL_MANIFEST,SANITY_VERSION if sanity else FULL_VERSION)
    if (out/"capture_runs.jsonl").exists():raise DecisionPremiseCaptureError("existing capture execution prohibits re-execution")
    sm={(x["scenario_id"],x["target_decision"]["id"]):x for x in snaps}; adapter=adapter_factory(); valid=invalid=provider=terminal=responses=0; aborted=False
    try:
      for i,e in enumerate(plan):
        s=sm[(e["scenario_id"],e["decision_id"])]; schema=PGEN_SCHEMA if e["condition_id"]=="PGEN" else pauto_provider_schema(); delivery=run_delivery_attempts(e,out/"capture_delivery_attempts.jsonl",lambda:adapter.generate(_capture_prompt(e["condition_id"],s),_config(m["experiment_version"]),response_schema=schema),sleep_fn)
        rec={**e,"raw_model_response":None,"canonical_payload":None,"payload_sha256":None,"validation_status":"provider_error","validation_error":None,"provider_error":None,"model_adapter":adapter.identifier}
        if delivery["result"] is None:provider+=1; err=delivery["last_error"]; rec["provider_error"]=f"{type(err).__name__}: {err}"
        else:
          responses+=1; rec["raw_model_response"]=delivery["result"].text
          try:
            raw=json.loads(delivery["result"].text); canonical,diag=(validate_pgen(raw,s) if e["condition_id"]=="PGEN" else validate_pauto(raw,s)); rec.update({"canonical_payload":canonical,"payload_sha256":_sha(_canonical(canonical)),"validation_status":"valid","diagnostics":diag}); valid+=1
          except (ValueError,TypeError,KeyError,CaptureValidationError) as exc:invalid+=1; rec.update({"validation_status":"invalid","validation_error":str(exc)})
        _append(out/"capture_runs.jsonl",rec); terminal+=1
        if i<len(plan)-1:sleep_fn(INTER_CALL_DELAY_SECONDS)
    except KeyboardInterrupt:aborted=True
    finally:adapter.close()
    complete=(terminal==len(plan) and responses==len(plan) and valid==len(plan) and invalid==provider==0 and not aborted)
    summary={"experiment_version":m["experiment_version"],"planned":len(plan),"terminal":terminal,"model_responses":responses,"valid":valid,"invalid":invalid,"provider_failures":provider,"aborted":aborted,"status":"PASS" if sanity and complete else "CAPTURE COMPLETE" if complete else "ABORTED" if aborted else "INCOMPLETE","downstream_eligible":complete and not sanity}
    (out/"capture_summary.json").write_bytes(_canonical(summary)); return summary
def execute_sanity(out:Path,**kw)->dict:return _execute_capture(out,True,**kw)
def execute_capture(out:Path,**kw)->dict:return _execute_capture(out,False,**kw)

def _capture_artifacts(out:Path)->dict:
    summary=json.loads((out/"capture_summary.json").read_text()); runs=[json.loads(x) for x in (out/"capture_runs.jsonl").read_text().splitlines() if x]
    if summary.get("downstream_eligible") is not True or len(runs)!=72 or any(x["validation_status"]!="valid" for x in runs):raise DecisionPremiseCaptureError("72/72 valid frozen captures required")
    result={}
    for x in runs:
        key=(x["scenario_id"],x["decision_id"],x["condition_id"])
        if key in result or _sha(_canonical(x["canonical_payload"]))!=x["payload_sha256"]:raise DecisionPremiseCaptureError("capture uniqueness/hash failure")
        result[key]=x["canonical_payload"]
    if len(result)!=72:raise DecisionPremiseCaptureError("capture coverage failure")
    return result
def context_bundle(s:dict,c:str,artifacts:dict)->dict:
    order=[d["id"] for d in sorted(s["candidate"]["decisions"],key=lambda d:(d["made_at"],d["id"]))]
    if c=="P0":records=[]
    elif c=="PORACLE":records=oracle_records(s)
    else:records=[copy.deepcopy(artifacts[(s["id"],did,c)]) for did in order]
    if records and [x["target_decision_id"] for x in records]!=order:raise DecisionPremiseCaptureError("decision record ordering/association mismatch")
    return {"decision_records":records}
def _downstream_prompt(base:dict,bundle:dict)->str:return BASE_TASK_PROMPT+"\n\nCANDIDATE-VISIBLE SCENARIO:\n"+_compact(base)+"\n\nDECISION CONTEXT BUNDLE:\n"+_compact(bundle)
def execute_downstream(out:Path,adapter_factory:Callable[[],Any]=_dev_adapter_factory,sleep_fn:Callable[[float],None]=sleep)->dict:
    m,plan,_=_validate_pre_execute(out,FULL_MANIFEST,FULL_VERSION,"downstream_plan.json"); artifacts=_capture_artifacts(out)
    if (out/"downstream_runs.jsonl").exists():raise DecisionPremiseCaptureError("existing downstream execution prohibits re-execution")
    scenarios={x["id"]:x for x in _dev()}; adapter=adapter_factory(); terminal=valid=invalid=provider=0; aborted=False
    try:
      for i,e in enumerate(plan):
        s=scenarios[e["scenario_id"]]; base=normalized_base(s); bundle=context_bundle(s,e["condition_id"],artifacts); delivery=run_delivery_attempts(e,out/"downstream_delivery_attempts.jsonl",lambda:adapter.generate(_downstream_prompt(base,bundle),_config(FULL_VERSION),response_schema=DISCOVERY_RESPONSE_JSON_SCHEMA),sleep_fn); rec={**e,"raw_model_response":None,"parsed_candidate_response":None,"validation_status":"provider_error","provider_error":None,"context_bundle_sha256":_sha(_canonical(bundle))}
        if delivery["result"] is None:provider+=1;err=delivery["last_error"];rec["provider_error"]=f"{type(err).__name__}: {err}"
        else:
          rec["raw_model_response"]=delivery["result"].text
          try:rec["parsed_candidate_response"]=parse_discovery_response(delivery["result"].text,[x["id"] for x in base["decisions"]]);rec["validation_status"]="valid";valid+=1
          except OutputValidationError as exc:rec["validation_status"]="invalid";rec["validation_error"]=str(exc);invalid+=1
        _append(out/"downstream_runs.jsonl",rec);terminal+=1
        if i<len(plan)-1:sleep_fn(INTER_CALL_DELAY_SECONDS)
    except KeyboardInterrupt:aborted=True
    finally:adapter.close()
    authorized=terminal==valid==48 and invalid==provider==0 and not aborted; summary={"planned":48,"terminal":terminal,"valid":valid,"invalid":invalid,"provider_failures":provider,"aborted":aborted,"analysis_authorized":authorized};(out/"downstream_summary.json").write_bytes(_canonical(summary));return summary

def _errors(rows:list[dict])->set[tuple[str,str,str]]:
    return {(x["scenario_id"],x["decision_id"],f) for x in rows for f in ("materially_dependent","still_justified") if x["true_"+f]!=x["predicted_"+f]}
def classify(rows:dict[str,list[dict]])->dict:
    e={c:_errors(rows[c]) for c in DOWNSTREAM_CONDITIONS}; oracle=e["P0"]-e["PORACLE"]; oracle_reg=e["PORACLE"]-e["P0"]
    corr={c:e["P0"]-e[c] for c in ("PGEN","PAUTO")}; reg={c:e[c]-e["P0"] for c in ("PGEN","PAUTO")}; recovered=oracle&corr["PAUTO"]
    if not oracle or oracle_reg:status="NO CONTEMPORARY PREMISE ADVANTAGE"
    elif reg["PAUTO"]:status="AUTO HARMFUL"
    elif recovered==oracle:status="AUTO GENERIC-EQUIVALENT" if oracle<=corr["PGEN"] and not reg["PGEN"] else "AUTO SUFFICIENT"
    elif recovered:status="AUTO PARTIAL"
    else:
        p0s=sum(x["true_dependency_strength"]!=x["predicted_dependency_strength"] for x in rows["P0"]); pas=sum(x["true_dependency_strength"]!=x["predicted_dependency_strength"] for x in rows["PAUTO"]);status="AUTO STRUCTURAL-ONLY" if pas<p0s else "AMBIGUOUS"
    return {"status":status,"oracle_corrections":[list(x) for x in sorted(oracle)],"oracle_regressions":[list(x) for x in sorted(oracle_reg)],"recovered_oracle_units":[list(x) for x in sorted(recovered)],"new_pauto_regressions":[list(x) for x in sorted(reg["PAUTO"])]}
def analyze(out:Path,analysis_dir:Path)->dict:
    if analysis_dir.exists():raise DecisionPremiseCaptureError("analysis directory exists")
    m,plan,_=_validate_pre_execute(out,FULL_MANIFEST,FULL_VERSION,"downstream_plan.json",runtime_integrity=False); summary=json.loads((out/"downstream_summary.json").read_text()); runs=[json.loads(x) for x in (out/"downstream_runs.jsonl").read_text().splitlines() if x]
    if summary.get("analysis_authorized") is not True or len(runs)!=48 or any(x["validation_status"]!="valid" for x in runs):raise DecisionPremiseCaptureError("complete 48-valid downstream experiment required")
    expected={(x["scenario_id"],x["condition_id"],x["repetition_id"]) for x in plan}; actual={(x["scenario_id"],x["condition_id"],x["repetition_id"]) for x in runs}
    if len(actual)!=48 or actual!=expected:raise DecisionPremiseCaptureError("downstream slot identity mismatch")
    scenarios={x["id"]:x for x in _dev()}; ledger=[]
    for run in runs:
      truth={x["decision_id"]:x for x in scenarios[run["scenario_id"]]["private"]["decision_labels"]}
      for p in run["parsed_candidate_response"]["decisions"]:
        t=truth[p["decision_id"]];ledger.append({"scenario_id":run["scenario_id"],"decision_id":p["decision_id"],"condition_id":run["condition_id"],"true_materially_dependent":t["materially_dependent"],"predicted_materially_dependent":p["materially_dependent"],"true_still_justified":t["still_justified"],"predicted_still_justified":p["still_justified"],"true_dependency_strength":t["dependency_strength"],"predicted_dependency_strength":p["dependency_strength"]})
    by={c:[x for x in ledger if x["condition_id"]==c] for c in DOWNSTREAM_CONDITIONS}; result={"analysis_version":"decision-premise-capture-analysis-v0.1","per_condition":{c:_condition_metrics(by[c]) for c in DOWNSTREAM_CONDITIONS},"contrasts":["P0_to_PORACLE","P0_to_PGEN","PGEN_to_PAUTO","P0_to_PAUTO","PAUTO_to_PORACLE"],"classification":classify(by),"forensic_endpoint":{c:next(x for x in by[c] if x["scenario_id"]=="dev-002" and x["decision_id"]=="d3") for c in DOWNSTREAM_CONDITIONS},"historical_results_used":False,"confirmation_authorized":False}
    analysis_dir.mkdir();(analysis_dir/"decision_premise_capture_analysis.json").write_bytes(_canonical(result));return result

def main(argv=None)->int:
    p=argparse.ArgumentParser();p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--analysis-dir",type=Path);p.add_argument("--sanity-dir",type=Path);g=p.add_mutually_exclusive_group(required=True)
    for x in ("prepare-sanity","execute-sanity","prepare-full","execute-capture","execute-downstream","analyze"):g.add_argument("--"+x,action="store_true")
    a=p.parse_args(argv)
    try:
      if a.prepare_sanity:r=prepare_sanity(a.output_dir)
      elif a.execute_sanity:r=execute_sanity(a.output_dir)
      elif a.prepare_full:
        if not a.sanity_dir:raise DecisionPremiseCaptureError("--prepare-full requires --sanity-dir")
        r=prepare_full(a.output_dir,a.sanity_dir)
      elif a.execute_capture:r=execute_capture(a.output_dir)
      elif a.execute_downstream:r=execute_downstream(a.output_dir)
      else:
        if not a.analysis_dir:raise DecisionPremiseCaptureError("--analysis-dir required")
        r=analyze(a.output_dir,a.analysis_dir)
      print(_compact(r));return 0
    except (DecisionPremiseCaptureError,CaptureValidationError,OSError,ValueError,KeyError) as e:print(str(e),file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
