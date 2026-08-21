"""Non-scientific PAUTO provider structured-output compatibility probe."""
from __future__ import annotations

import argparse, copy, json, sys
from pathlib import Path
from time import sleep
from typing import Any, Callable

from google.genai import types

from .decision_premise_capture import (
    PAUTO_INSTRUCTION, PAUTO_SCHEMA, PROTOCOL_SHA256, CaptureValidationError,
    _canonical, _compact, _config, _git, _now, _schema_sha, _sha,
    validate_pauto,
)
from .dev_experiment import (
    LOCATION, MODEL_ID, PROJECT_ID, SDK_PACKAGE, SDK_VERSION,
    _dev_adapter_factory, run_delivery_attempts,
)
from .models import ModelResponse

PROBE_VERSION = "pauto-provider-compatibility-probe-v0.1"
MANIFEST_TYPE = "pauto-provider-compatibility-probe-manifest-v0.1"
VARIANT_ORDER = ("V0", "V1", "V2", "V3")
MAX_PROVIDER_INVOCATIONS = 4
SYNTHETIC_SNAPSHOT = {
    "system_pre_change_context": {
        "agents": [{"id": "synthetic-agent", "role": "test role"}],
        "knowledge_before": [{"id": "synthetic-k1", "holder": "synthetic-agent", "statement": "Synthetic switch alpha is enabled.", "visibility": ["synthetic-agent"]}],
    },
    "strictly_earlier_recorded_transmissions": [],
    "strictly_earlier_system_recorded_decisions": [],
    "target_decision": {"id": "synthetic-d1", "agent_id": "synthetic-agent", "made_at": 1, "statement": "Use synthetic route beta."},
}
SYNTHETIC_PROMPT = PAUTO_INSTRUCTION + "\n\nNON-SCIENTIFIC SYNTHETIC PRE-CHANGE SNAPSHOT:\n" + _compact(SYNTHETIC_SNAPSHOT)

class ProbeError(RuntimeError): pass

def _remove_keywords(value: Any, keywords: set[str]) -> Any:
    if isinstance(value, dict): return {key: _remove_keywords(item, keywords) for key, item in value.items() if key not in keywords}
    if isinstance(value, list): return [_remove_keywords(item, keywords) for item in value]
    return copy.deepcopy(value)

def provider_variants() -> dict[str, dict[str, Any]]:
    v0 = copy.deepcopy(PAUTO_SCHEMA)
    v1 = _remove_keywords(v0, {"minItems", "maxItems"})
    v2 = _remove_keywords(v1, {"additionalProperties"})
    return {
        "V0": {"schema": v0, "schema_input_path": "response_json_schema"},
        "V1": {"schema": v1, "schema_input_path": "response_json_schema"},
        "V2": {"schema": v2, "schema_input_path": "response_json_schema"},
        "V3": {"schema": copy.deepcopy(v2), "schema_input_path": "response_schema"},
    }

def _config_hash(variant: dict[str, Any]) -> str:
    return _sha(_canonical({"response_mime_type": "application/json", "schema_input_path": variant["schema_input_path"], "schema": variant["schema"]}))

def _variant_diff(before: Any, after: Any, path: str = "") -> list[tuple[str, str]]:
    changes=[]
    if isinstance(before,dict) and isinstance(after,dict):
        for key in sorted(set(before)|set(after)):
            p=f"{path}/{key}"
            if key not in after:changes.append((p,"removed"))
            elif key not in before:changes.append((p,"added"))
            else:changes.extend(_variant_diff(before[key],after[key],p))
    elif before!=after:changes.append((path,"changed"))
    return changes

def _invoke(adapter: Any, variant: dict[str, Any]) -> ModelResponse:
    if variant["schema_input_path"] == "response_json_schema":
        return adapter.generate(SYNTHETIC_PROMPT, _config(PROBE_VERSION), response_schema=variant["schema"])
    config=types.GenerateContentConfig(response_mime_type="application/json",response_schema=variant["schema"])
    response=adapter.client.models.generate_content(model=MODEL_ID,contents=SYNTHETIC_PROMPT,config=config)
    usage=getattr(response,"usage_metadata",None)
    return ModelResponse(text=getattr(response,"text",None) or "",model_name=MODEL_ID,model_version=getattr(response,"model_version",None),input_tokens=getattr(usage,"prompt_token_count",None) if usage else None,output_tokens=getattr(usage,"candidates_token_count",None) if usage else None)

def build_manifest(implementation_sha: str) -> dict[str, Any]:
    variants=provider_variants()
    return {
        "manifest_type":MANIFEST_TYPE,"probe_version":PROBE_VERSION,"implementation_sha":implementation_sha,
        "sdk_package":SDK_PACKAGE,"sdk_version":SDK_VERSION,"model_id":MODEL_ID,"provider":"Google Cloud Agent Platform / Vertex","project_id":PROJECT_ID,"location":LOCATION,
        "variant_order":list(VARIANT_ORDER),"variants":{name:{"schema_input_path":v["schema_input_path"],"provider_schema_sha256":_schema_sha(v["schema"]),"provider_config_sha256":_config_hash(v)} for name,v in variants.items()},
        "pauto_scientific_schema_sha256":_schema_sha(PAUTO_SCHEMA),"local_validator":"validate_pauto unchanged",
        "scientific_observation":False,"benchmark_evaluation_authorized":False,"artifact_reuse_for_science":False,"dev_access_authorized":False,"sealed_holdout_access_authorized":False,"max_provider_invocations":4,"created_at_utc":_now(),
    }

def run_probe(output_dir: Path, adapter_factory: Callable[[],Any]=_dev_adapter_factory, sleep_fn: Callable[[float],None]=sleep) -> dict[str,Any]:
    if output_dir.exists():raise ProbeError("probe output directory already exists")
    output_dir.mkdir(); variants=provider_variants(); manifest=build_manifest(_git("rev-parse","HEAD"));(output_dir/"probe_manifest.json").write_bytes(_canonical(manifest))
    adapter=adapter_factory(); outcomes=[]; selected=None; invocations=0
    try:
        for name in VARIANT_ORDER:
            variant=variants[name]
            entry={"variant_id":name,"observation_kind":"non_scientific_provider_compatibility_probe","scientific_observation":False}
            def invoke():
                nonlocal invocations
                if invocations>=MAX_PROVIDER_INVOCATIONS:raise ProbeError("global provider invocation budget exhausted")
                invocations+=1;return _invoke(adapter,variant)
            delivery=run_delivery_attempts(entry,output_dir/"probe_delivery_attempts.jsonl",invoke,sleep_fn)
            outcome={"variant_id":name,"provider_schema_sha256":_schema_sha(variant["schema"]),"provider_config_sha256":_config_hash(variant),"schema_input_path":variant["schema_input_path"],"delivery_attempts":delivery["attempts_used"],"model_response_obtained":delivery["result"] is not None,"http_status_code":delivery["http_status_code"],"failure_classification":delivery["failure_classification"],"retryable":False,"json_parsed":False,"local_scientific_validation_passed":False,"local_validation_error":None}
            if delivery["result"] is not None:
                selected=name;raw=delivery["result"].text;outcome["raw_response"]=raw
                try:value=json.loads(raw);outcome["json_parsed"]=True
                except (ValueError,TypeError) as exc:outcome["local_validation_error"]=str(exc)
                else:
                    try:validate_pauto(value,{"scenario_id":"synthetic","**":None,**SYNTHETIC_SNAPSHOT});outcome["local_scientific_validation_passed"]=True
                    except (CaptureValidationError,ValueError,TypeError,KeyError) as exc:outcome["local_validation_error"]=str(exc)
            else:
                err=delivery["last_error"];outcome["error"]=f"{type(err).__name__}: {err}";outcome["retryable"]=delivery["failure_classification"] in {"timeout","http_status"} and delivery["http_status_code"] in {408,429,500,502,503,504}
            outcomes.append(outcome)
            with (output_dir/"probe_outcomes.jsonl").open("a",encoding="utf-8",newline="\n") as f:f.write(_compact(outcome)+"\n")
            if selected is not None or invocations>=MAX_PROVIDER_INVOCATIONS:break
    finally:adapter.close()
    summary={"probe_version":PROBE_VERSION,"status":"ACCEPTED_VARIANT_FOUND" if selected else "PROBE_EXHAUSTED","selected_first_accepted_variant":selected,"variants_attempted":[x["variant_id"] for x in outcomes],"live_provider_invocations":invocations,"scientific_observation":False,"benchmark_evaluation_authorized":False,"artifact_reuse_for_science":False}
    (output_dir/"probe_summary.json").write_bytes(_canonical(summary));return summary

def main(argv=None)->int:
    p=argparse.ArgumentParser();p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--execute-probe",action="store_true",required=True);a=p.parse_args(argv)
    try:print(_compact(run_probe(a.output_dir)));return 0
    except (ProbeError,OSError,ValueError,KeyError) as exc:print(str(exc),file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
