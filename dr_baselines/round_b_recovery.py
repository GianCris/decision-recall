from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Callable

from dr_bench import candidate_view, evaluate_discovery, load_scenario

from .dev_experiment import (
    DELIVERY_BACKOFF_SECONDS, DELIVERY_POLICY_VERSION, LOCATION,
    MAX_DELIVERY_ATTEMPTS, MODEL_ID, PROJECT_ID, RETRYABLE_HTTP_STATUS_CODES,
    SDK_PACKAGE, SDK_VERSION, TRANSPORT_ATTEMPTS, TRANSPORT_TIMEOUT_MS,
    TRANSPORT_TIMEOUT_SECONDS, _dev_adapter_factory, run_delivery_attempts,
)
from .output import (
    DISCOVERY_RESPONSE_JSON_SCHEMA, DISCOVERY_RESPONSE_SCHEMA_VERSION,
    OutputValidationError, parse_discovery_response,
)
from .round_b import (
    EXPERIMENT_VERSION as ORIGINAL_EXPERIMENT_VERSION,
    PROTOCOL_SHA256 as ROUND_B_PROTOCOL_SHA256,
    _canonical_json, _config as original_config, build_stage2_prompt,
    schema_sha256,
)

RECOVERY_EXPERIMENT_VERSION = "round-b-infrastructure-recovery-v0.1"
RECOVERY_MANIFEST_TYPE = "round-b-infrastructure-recovery-manifest-v0.1"
RECOVERY_PROTOCOL_PATH = Path("docs/ROUND_B_INFRASTRUCTURE_RECOVERY_V0.1.md")
RECOVERY_PROTOCOL_SHA256 = "bf3b76dbfc6635a7aff4c6f7acad55b75f59b205e816eed70fd989e017353652"
ORIGINAL_IMPLEMENTATION_SHA = "167ecfa50c871c74d0aee4ed9abd9feab40fc923"
ORIGINAL_MANIFEST_TYPE = "round-b-screening-manifest-v0.2"
EXPECTED_DEPENDENCY_SHA256 = "98ba67a06bc97cc14ad322f4e580a9d3e232aa3c777fd580eb2823563fb367d5"
EXPECTED_CANDIDATE_INPUT_SHA256 = "e91a3367a7179decc4cd7c874de38046ade08989a8b4daad19d046531ab667e4"
EXPECTED_EFFECTIVE_PROMPT_SHA256 = "20302ba0ab1aa8ef58c7af6c13f9bbb500c16ca1c7b741266986a8da003072a1"
EXPECTED_DISCOVERY_SCHEMA_SHA256 = "c1da8e87a79950b25c57bfdd411a44c6482ec15cbadeca69b6019e7fbda52ce5"
PLAN_FILENAME = "recovery_execution_plan.json"
MANIFEST_FILENAME = "recovery_manifest.json"
IDENTITY_FILENAME = "identity_evidence.json"
CANDIDATE_FILENAME = "candidate_visible_input.json"
DEPENDENCY_FILENAME = "dependency_payload.json"
PROMPT_FILENAME = "effective_prompt.txt"
SCHEMA_FILENAME = "discovery_response_schema.json"
DELIVERY_FILENAME = "recovery_delivery_attempts.jsonl"


class RecoveryError(RuntimeError):
    pass


class IdentityProofError(RecoveryError):
    pass


@dataclass(frozen=True)
class EligibleSlot:
    original_global_execution_index: int
    scenario_id: str
    condition_id: str
    stage_id: str
    observation_kind: str
    repetition_id: str
    candidate_view_mode: str
    dependency_stage: str
    original_failed_attempt_started_at_utc: str
    original_failed_attempt_completed_at_utc: str
    original_http_status_code: int
    dependency_artifact_sha256: str
    dependency_canonical_bytes: bytes
    historical_experiment_config: dict[str, Any]
    historical_model_name: str
    historical_model_adapter: str

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("dependency_canonical_bytes")
        value.pop("historical_experiment_config")
        value.pop("historical_model_name")
        value.pop("historical_model_adapter")
        return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _git_branch() -> str:
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _tracked_clean() -> bool:
    return not subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], check=True, capture_output=True, text=True).stdout.strip()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def recovery_protocol_sha256() -> str:
    return _sha(RECOVERY_PROTOCOL_PATH.read_bytes())


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _matching_jsonl(path: Path, index: int) -> list[dict[str, Any]]:
    marker = re.compile(rf'"global_execution_index"\s*:\s*{index}(?:\D|$)')
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if marker.search(line)]


def _evaluation_indices(path: Path) -> set[int]:
    pattern = re.compile(r'"global_execution_index"\s*:\s*(\d+)')
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.search(line)
        if match:
            result.add(int(match.group(1)))
    return result


def _source_hashes(original_dir: Path) -> dict[str, str]:
    return {p.name: _sha(p.read_bytes()) for p in sorted(original_dir.iterdir(), key=lambda p: p.name) if p.is_file()}


CANDIDATE_INPUT_SOURCE_PATHS = (
    "dr_bench/__init__.py", "dr_bench/catalog.py", "dr_bench/views.py",
    "dr_bench/validation.py", "dr_bench/paths.py", "dr_bench/simulator.py",
    "dr_bench/data/dev.jsonl", "dr_bench/data/holdout.jsonl",
    "dr_bench/data/interaction_chains.json", "dr_baselines/round_b.py",
)
PROMPT_SOURCE_PATHS = ("dr_baselines/baselines.py", "dr_baselines/round_b.py")
SCHEMA_SOURCE_PATHS = ("dr_baselines/output.py", "dr_baselines/round_b.py")


def _git_object_proof(paths: tuple[str, ...]) -> dict[str, Any]:
    """Compare committed source objects to the original scientific commit."""
    files = {}
    all_equal = True
    for path in paths:
        original = subprocess.run(["git", "show", f"{ORIGINAL_IMPLEMENTATION_SHA}:{path}"], check=True, capture_output=True).stdout
        current = subprocess.run(["git", "show", f"HEAD:{path}"], check=True, capture_output=True).stdout
        equal = current == original
        all_equal &= equal
        files[path] = {"original_sha256": _sha(original), "head_sha256": _sha(current), "equal": equal}
    return {"reconstruction_source_commit": ORIGINAL_IMPLEMENTATION_SHA, "current_commit": _git_sha(), "files": files, "all_equal": all_equal}


def _scientific_source_proofs() -> dict[str, Any]:
    return {
        "candidate_visible_input": _git_object_proof(CANDIDATE_INPUT_SOURCE_PATHS),
        "effective_stage2_prompt": _git_object_proof(PROMPT_SOURCE_PATHS),
        "discovery_schema_object": _git_object_proof(SCHEMA_SOURCE_PATHS),
    }


def verify_original_source(original_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    required = {"experiment_manifest.json", "execution_plan.json", "delivery_attempts.jsonl", "terminal_states.jsonl", "runs.jsonl", "evaluations.jsonl", "stage1_artifacts.jsonl", "summary.json"}
    if not original_dir.is_dir() or not required <= {p.name for p in original_dir.iterdir()}:
        raise RecoveryError("original Round B experiment is missing required immutable artifacts")
    manifest = _read_json(original_dir / "experiment_manifest.json")
    plan_bytes = (original_dir / "execution_plan.json").read_bytes()
    plan = json.loads(plan_bytes)
    summary = _read_json(original_dir / "summary.json")
    checks = (
        manifest.get("manifest_type") == ORIGINAL_MANIFEST_TYPE,
        manifest.get("experiment_version") == ORIGINAL_EXPERIMENT_VERSION,
        manifest.get("git_commit_sha") == ORIGINAL_IMPLEMENTATION_SHA,
        manifest.get("round_b_protocol_sha256") == ROUND_B_PROTOCOL_SHA256,
        manifest.get("execution_plan_sha256") == _sha(plan_bytes),
        manifest.get("model_id") == MODEL_ID,
        manifest.get("project_id") == PROJECT_ID,
        manifest.get("location") == LOCATION,
        summary.get("experiment_status") == "completed",
        summary.get("classification_status") == "INCOMPLETE / INFRASTRUCTURE",
        summary.get("provider_failures") == 1,
        summary.get("abort_reason") is None,
    )
    if not all(checks):
        raise RecoveryError("original Round B source identity or infrastructure accounting is inconsistent")
    return manifest, plan, _source_hashes(original_dir)


def find_recovery_eligible_slots(original_dir: Path) -> list[EligibleSlot]:
    _, plan, _ = verify_original_source(original_dir)
    terminals = _jsonl(original_dir / "terminal_states.jsonl")
    provider_terminals = [x for x in terminals if x.get("validation_status") == "provider_error"]
    evaluation_indices = _evaluation_indices(original_dir / "evaluations.jsonl")
    artifacts = _jsonl(original_dir / "stage1_artifacts.jsonl")
    eligible = []
    for terminal in provider_terminals:
        index = terminal.get("global_execution_index")
        entries = [x for x in plan if x.get("global_execution_index") == index]
        runs = _matching_jsonl(original_dir / "runs.jsonl", index)
        lifecycle = [x for x in _matching_jsonl(original_dir / "delivery_attempts.jsonl", index) if x.get("event") == "delivery_attempt_completed"]
        if len(entries) != 1 or len(runs) != 1 or len(lifecycle) != 1:
            continue
        entry, run, failure = entries[0], runs[0], lifecycle[0]
        dependency = entry.get("dependency_artifact_required")
        dependencies = [x for x in artifacts if x.get("scenario_id") == entry.get("scenario_id") and x.get("stage_id") == dependency]
        if len(dependencies) != 1 or not isinstance(dependencies[0].get("canonical_bytes_utf8"), str):
            continue
        artifact = dependencies[0]
        artifact_bytes = artifact["canonical_bytes_utf8"].encode("utf-8")
        artifact_sha = _sha(artifact_bytes)
        checks = (
            entry.get("observation_kind") == "final",
            failure.get("outcome") == "pre_response_failure",
            failure.get("model_response_obtained") is False,
            failure.get("will_retry") is False,
            run.get("validation_status") == "provider_error",
            run.get("raw_model_response") == "",
            run.get("parsed_candidate_response") is None,
            terminal.get("raw_model_response") == "",
            terminal.get("parsed_candidate_response") is None,
            index not in evaluation_indices,
            artifact.get("model_call_executed") is True,
            artifact_sha == artifact.get("artifact_sha256"),
            artifact_sha == artifact.get("artifact_envelope", {}).get("artifact_sha256"),
            artifact_sha == run.get("artifact_sha256"),
        )
        if not all(checks):
            continue
        historical_config = run.get("experiment_config")
        if not isinstance(historical_config, dict) or not isinstance(run.get("model_name"), str) or not isinstance(run.get("model_adapter"), str):
            continue
        eligible.append(EligibleSlot(index, entry["scenario_id"], entry["condition_id"], entry["stage_id"], entry["observation_kind"], entry["repetition_id"], entry["candidate_view_mode"], dependency, failure["started_at_utc"], failure["completed_at_utc"], failure["http_status_code"], artifact_sha, artifact_bytes, historical_config, run["model_name"], run["model_adapter"]))
    return eligible


def _scientific_inputs(slot: EligibleSlot) -> tuple[dict[str, Any], bytes, bytes, bytes]:
    scenario = load_scenario(slot.scenario_id)
    public = {key: value for key, value in scenario.items() if key != "private"}
    visible = candidate_view(public, "discovery", slot.candidate_view_mode)
    candidate_bytes = _canonical_json(visible)
    prompt_bytes = build_stage2_prompt(slot.condition_id, visible, slot.dependency_canonical_bytes).encode("utf-8")
    schema_bytes = _canonical_json(DISCOVERY_RESPONSE_JSON_SCHEMA)
    return visible, candidate_bytes, prompt_bytes, schema_bytes


def _identity_evidence(slot: EligibleSlot, candidate_bytes: bytes, prompt_bytes: bytes, schema_bytes: bytes, original_manifest: dict[str, Any], source_proofs: dict[str, Any]) -> dict[str, Any]:
    schema_digest = schema_sha256(DISCOVERY_RESPONSE_JSON_SCHEMA)
    candidate_sha = _sha(candidate_bytes)
    prompt_sha = _sha(prompt_bytes)
    # RunRecord JSON persistence converts tuples to arrays; compare the exact
    # persisted JSON representation rather than Python container incidentalities.
    current_config = json.loads(json.dumps(original_config().to_dict()))
    historical_provider = {key: original_manifest.get(key) for key in ("provider", "project_id", "location", "model_id", "sdk_package", "sdk_version")}
    required_provider = {"provider": "Google Cloud Agent Platform / Vertex", "project_id": PROJECT_ID, "location": LOCATION, "model_id": MODEL_ID, "sdk_package": SDK_PACKAGE, "sdk_version": SDK_VERSION}
    candidate_source = source_proofs["candidate_visible_input"]
    prompt_source = source_proofs["effective_stage2_prompt"]
    schema_source = source_proofs["discovery_schema_object"]
    rows = {
        "candidate_visible_input": {"class": "B" if candidate_source["all_equal"] else "C", "proven": candidate_source["all_equal"] and candidate_sha == EXPECTED_CANDIDATE_INPUT_SHA256, "historical_source": "immutable DEV data and loader/view path at original implementation commit", "reconstruction_source_commit": ORIGINAL_IMPLEMENTATION_SHA, "source_file_proof": candidate_source, "historical_prepared_sha256": EXPECTED_CANDIDATE_INPUT_SHA256, "reconstructed_sha256": candidate_sha, "comparison_equal": candidate_sha == EXPECTED_CANDIDATE_INPUT_SHA256},
        "candidate_view_mode": {"class": "A", "proven": slot.candidate_view_mode == "implicit", "historical_source": "execution_plan.json and failed runs.jsonl", "historical_value": slot.candidate_view_mode, "required_value": "implicit", "comparison_equal": slot.candidate_view_mode == "implicit"},
        "dependency_canonical_bytes": {"class": "A", "proven": _sha(slot.dependency_canonical_bytes) == slot.dependency_artifact_sha256, "historical_source": "stage1_artifacts.jsonl canonical_bytes_utf8", "historical_persisted_sha256": slot.dependency_artifact_sha256, "recomputed_sha256": _sha(slot.dependency_canonical_bytes), "comparison_equal": _sha(slot.dependency_canonical_bytes) == slot.dependency_artifact_sha256},
        "dependency_artifact_sha256": {"class": "A", "proven": slot.dependency_artifact_sha256 == EXPECTED_DEPENDENCY_SHA256, "historical_source": "Stage-1 artifact, envelope, and failed RunRecord", "historical_persisted_sha256": slot.dependency_artifact_sha256, "required_sha256": EXPECTED_DEPENDENCY_SHA256, "comparison_equal": slot.dependency_artifact_sha256 == EXPECTED_DEPENDENCY_SHA256},
        "effective_stage2_prompt_bytes": {"class": "B" if prompt_source["all_equal"] and candidate_source["all_equal"] else "C", "proven": prompt_source["all_equal"] and candidate_source["all_equal"] and prompt_sha == EXPECTED_EFFECTIVE_PROMPT_SHA256 and _sha(slot.dependency_canonical_bytes) == EXPECTED_DEPENDENCY_SHA256, "historical_source": "original BASE_TASK_PROMPT/build_stage2_prompt/canonical formatting plus proven candidate and dependency bytes", "reconstruction_source_commit": ORIGINAL_IMPLEMENTATION_SHA, "source_file_proof": prompt_source, "candidate_source_proof_equal": candidate_source["all_equal"], "dependency_sha256": _sha(slot.dependency_canonical_bytes), "historical_prepared_sha256": EXPECTED_EFFECTIVE_PROMPT_SHA256, "reconstructed_sha256": prompt_sha, "comparison_equal": prompt_sha == EXPECTED_EFFECTIVE_PROMPT_SHA256},
        "effective_stage2_prompt_sha256": {"class": "B" if prompt_source["all_equal"] else "C", "proven": prompt_source["all_equal"] and prompt_sha == EXPECTED_EFFECTIVE_PROMPT_SHA256, "historical_source": "deterministically reconstructed effective prompt bytes", "reconstruction_source_commit": ORIGINAL_IMPLEMENTATION_SHA, "historical_prepared_sha256": EXPECTED_EFFECTIVE_PROMPT_SHA256, "reconstructed_sha256": prompt_sha, "comparison_equal": prompt_sha == EXPECTED_EFFECTIVE_PROMPT_SHA256},
        "discovery_schema_object": {"class": "B" if schema_source["all_equal"] else "C", "proven": schema_source["all_equal"] and schema_digest == original_manifest.get("discovery_schema_sha256") == EXPECTED_DISCOVERY_SCHEMA_SHA256, "historical_source": "original output schema source at implementation commit", "reconstruction_source_commit": ORIGINAL_IMPLEMENTATION_SHA, "source_file_proof": schema_source, "historical_persisted_sha256": original_manifest.get("discovery_schema_sha256"), "reconstructed_contract_sha256": schema_digest, "canonical_file_sha256": _sha(schema_bytes), "comparison_equal": schema_digest == original_manifest.get("discovery_schema_sha256")},
        "discovery_schema_version_sha": {"class": "A", "proven": original_manifest.get("discovery_schema_version") == DISCOVERY_RESPONSE_SCHEMA_VERSION and original_manifest.get("discovery_schema_sha256") == schema_digest == EXPECTED_DISCOVERY_SCHEMA_SHA256, "historical_source": "experiment_manifest.json", "historical_version": original_manifest.get("discovery_schema_version"), "historical_sha256": original_manifest.get("discovery_schema_sha256"), "required_version": DISCOVERY_RESPONSE_SCHEMA_VERSION, "required_sha256": EXPECTED_DISCOVERY_SCHEMA_SHA256, "comparison_equal": original_manifest.get("discovery_schema_version") == DISCOVERY_RESPONSE_SCHEMA_VERSION and original_manifest.get("discovery_schema_sha256") == schema_digest},
        "model_identifier": {"class": "A", "proven": original_manifest.get("model_id") == slot.historical_model_name == MODEL_ID and slot.historical_model_adapter == "google-genai-vertex-gemini-3.7-flash-v0.1", "historical_source": "experiment_manifest.json and failed runs.jsonl", "manifest_value": original_manifest.get("model_id"), "run_record_value": slot.historical_model_name, "run_record_adapter": slot.historical_model_adapter, "required_value": MODEL_ID, "required_adapter": "google-genai-vertex-gemini-3.7-flash-v0.1", "comparison_equal": original_manifest.get("model_id") == slot.historical_model_name == MODEL_ID and slot.historical_model_adapter == "google-genai-vertex-gemini-3.7-flash-v0.1"},
        "generation_configuration": {"class": "A", "proven": slot.historical_experiment_config == current_config, "historical_source": "failed-slot runs.jsonl experiment_config", "historical_persisted_value": slot.historical_experiment_config, "recovery_required_value": current_config, "comparison_equal": slot.historical_experiment_config == current_config},
        "provider_location_configuration": {"class": "A", "proven": historical_provider == required_provider, "historical_source": "experiment_manifest.json", "historical_persisted_value": historical_provider, "recovery_required_value": required_provider, "comparison_equal": historical_provider == required_provider},
        "condition_stage_identity": {"class": "A", "proven": slot.condition_id == "RC0" and slot.stage_id == "RC0_STAGE2", "historical_source": "execution plan, lifecycle, terminal record, and failed RunRecord", "historical_persisted_value": slot.public_dict(), "required_value": {"condition_id": "RC0", "stage_id": "RC0_STAGE2"}, "comparison_equal": slot.condition_id == "RC0" and slot.stage_id == "RC0_STAGE2"},
    }
    return {"components": rows, "category_c_count": sum(x["class"] == "C" for x in rows.values()), "all_proven": all(x["proven"] for x in rows.values())}


def build_recovery_plan(slot: EligibleSlot) -> list[dict[str, Any]]:
    return [{"recovery_scientific_observation_index": 1, "original_global_execution_index": slot.original_global_execution_index, "scenario_id": slot.scenario_id, "condition_id": slot.condition_id, "stage_id": slot.stage_id, "observation_kind": slot.observation_kind, "repetition_id": slot.repetition_id, "candidate_view_mode": slot.candidate_view_mode, "dependency_artifact_required": slot.dependency_stage, "expected_output_contract": DISCOVERY_RESPONSE_SCHEMA_VERSION, "infrastructure_recovered": True, "out_of_original_order": True}]


def prepare_recovery(original_dir: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise RecoveryError("recovery output directory already exists")
    if recovery_protocol_sha256() != RECOVERY_PROTOCOL_SHA256:
        raise RecoveryError("recovery protocol SHA differs from the frozen authority")
    if not _tracked_clean():
        raise RecoveryError("tracked worktree must be clean before recovery PREPARE")
    original_manifest, _, original_hashes = verify_original_source(original_dir)
    source_proofs = _scientific_source_proofs()
    eligible = find_recovery_eligible_slots(original_dir)
    if len(eligible) != 1:
        raise RecoveryError(f"recovery requires exactly one eligible slot; found {len(eligible)}")
    slot = eligible[0]
    if slot.dependency_artifact_sha256 != EXPECTED_DEPENDENCY_SHA256:
        raise IdentityProofError("original dependency artifact SHA differs from the frozen value")
    _, candidate_bytes, prompt_bytes, schema_bytes = _scientific_inputs(slot)
    evidence = _identity_evidence(slot, candidate_bytes, prompt_bytes, schema_bytes, original_manifest, source_proofs)
    if evidence["category_c_count"] or not evidence["all_proven"]:
        raise IdentityProofError("RECOVERY BLOCKED — ORIGINAL SCIENTIFIC INPUT IDENTITY CANNOT BE PROVEN")
    plan_bytes = _canonical_json(build_recovery_plan(slot))
    manifest = {
        "manifest_type": RECOVERY_MANIFEST_TYPE, "experiment_version": RECOVERY_EXPERIMENT_VERSION,
        "recovery_protocol_sha256": RECOVERY_PROTOCOL_SHA256, "recovery_implementation_git_sha": _git_sha(),
        "branch": _git_branch(), "created_at_utc": _utc_now(),
        "original_experiment_directory_identity": original_dir.name,
        "original_experiment_version": original_manifest["experiment_version"], "original_manifest_type": original_manifest["manifest_type"],
        "original_implementation_git_sha": original_manifest["git_commit_sha"], "original_round_b_protocol_sha256": original_manifest["round_b_protocol_sha256"],
        "original_execution_plan_sha256": original_manifest["execution_plan_sha256"], "original_source_file_sha256": original_hashes,
        "scientific_source_proofs": source_proofs,
        "eligible_slot_count": 1, "eligible_slot": slot.public_dict(), "planned_recovery_scientific_observations": 1,
        "recovery_execution_plan_sha256": _sha(plan_bytes), "candidate_input_sha256": _sha(candidate_bytes),
        "dependency_artifact_sha256": slot.dependency_artifact_sha256, "effective_prompt_sha256": _sha(prompt_bytes),
        "discovery_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION, "discovery_schema_sha256": schema_sha256(DISCOVERY_RESPONSE_JSON_SCHEMA),
        "model_id": MODEL_ID, "model_adapter": "google-genai-vertex-gemini-3.7-flash-v0.1", "provider": "Google Cloud Agent Platform / Vertex", "project_id": PROJECT_ID, "location": LOCATION,
        "experiment_config": original_config().to_dict(),
        "transport": {"delivery_policy_version": DELIVERY_POLICY_VERSION, "sdk_attempts": TRANSPORT_ATTEMPTS, "max_delivery_attempts": MAX_DELIVERY_ATTEMPTS, "retryable_http_status_codes": list(RETRYABLE_HTTP_STATUS_CODES), "backoff_seconds": list(DELIVERY_BACKOFF_SECONDS), "jitter": False, "timeout_ms": TRANSPORT_TIMEOUT_MS, "timeout_seconds": TRANSPORT_TIMEOUT_SECONDS, "first_model_response_wins": True, "concurrency": 1},
        "candidate_view_mode": slot.candidate_view_mode, "infrastructure_recovered": True, "out_of_original_order": True,
        "original_experiment_status": "INCOMPLETE / INFRASTRUCTURE", "execute_eligible": True,
        "scientific_result_blindness": "infrastructure/lifecycle metadata and immutable input/config/artifact only",
        "recovered_view_support": {"contains_infrastructure_recovered_observation": True, "out_of_original_order_recovery_count": 1, "original_experiment_status": "INCOMPLETE / INFRASTRUCTURE", "sensitivity_reporting_required": True, "sensitivity_evaluated_during_prepare": False},
    }
    output_dir.mkdir(parents=True)
    for name, data in ((PLAN_FILENAME, plan_bytes), (MANIFEST_FILENAME, _canonical_json(manifest)), (IDENTITY_FILENAME, _canonical_json(evidence)), (CANDIDATE_FILENAME, candidate_bytes), (DEPENDENCY_FILENAME, slot.dependency_canonical_bytes), (PROMPT_FILENAME, prompt_bytes), (SCHEMA_FILENAME, schema_bytes)):
        (output_dir / name).write_bytes(data)
    return manifest


def _load_prepared_recovery(original_dir: Path, output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not output_dir.is_dir() or not (output_dir / MANIFEST_FILENAME).exists():
        raise RecoveryError("compatible prepared recovery manifest is required")
    if (output_dir / "experiment_manifest.json").exists() or (output_dir / "sanity_manifest.json").exists():
        raise RecoveryError("ordinary Round B or sanity directory cannot be used for recovery")
    if any((output_dir / name).exists() for name in (DELIVERY_FILENAME, "recovery_run.json", "recovery_evaluation.json", "recovery_summary.json")):
        raise RecoveryError("prepared recovery already contains execution artifacts; resume is not authorized")
    manifest = _read_json(output_dir / MANIFEST_FILENAME)
    plan_bytes = (output_dir / PLAN_FILENAME).read_bytes()
    plan = json.loads(plan_bytes)
    evidence = _read_json(output_dir / IDENTITY_FILENAME)
    if manifest.get("manifest_type") != RECOVERY_MANIFEST_TYPE or manifest.get("experiment_version") != RECOVERY_EXPERIMENT_VERSION:
        raise RecoveryError("incompatible recovery manifest")
    if manifest.get("recovery_implementation_git_sha") != _git_sha() or not _tracked_clean():
        raise RecoveryError("recovery implementation Git identity or tracked worktree differs from PREPARE")
    if manifest.get("recovery_execution_plan_sha256") != _sha(plan_bytes) or len(plan) != 1:
        raise RecoveryError("recovery plan identity differs from PREPARE")
    if evidence.get("category_c_count") or not evidence.get("all_proven") or not manifest.get("execute_eligible"):
        raise IdentityProofError("recovery identity gate does not authorize execution")
    if _source_hashes(original_dir) != manifest.get("original_source_file_sha256"):
        raise RecoveryError("original experiment artifacts changed after PREPARE")
    for name, expected in ((CANDIDATE_FILENAME, manifest["candidate_input_sha256"]), (DEPENDENCY_FILENAME, manifest["dependency_artifact_sha256"]), (PROMPT_FILENAME, manifest["effective_prompt_sha256"])):
        if _sha((output_dir / name).read_bytes()) != expected:
            raise IdentityProofError(f"prepared identity artifact changed: {name}")
    if schema_sha256(_read_json(output_dir / SCHEMA_FILENAME)) != manifest["discovery_schema_sha256"]:
        raise IdentityProofError("prepared Discovery schema changed")
    return manifest, plan[0]


def execute_recovery(original_dir: Path, output_dir: Path, adapter_factory: Callable[[], Any] = _dev_adapter_factory, sleep_fn: Callable[[float], None] = sleep) -> dict[str, Any]:
    manifest, entry = _load_prepared_recovery(original_dir, output_dir)
    adapter = adapter_factory()
    invoked = _utc_now()
    try:
        prompt = (output_dir / PROMPT_FILENAME).read_text(encoding="utf-8")
        schema = _read_json(output_dir / SCHEMA_FILENAME)
        def invoke() -> Any:
            return adapter.generate(prompt, original_config(), response_schema=schema)
        try:
            delivery = run_delivery_attempts(entry, output_dir / DELIVERY_FILENAME, invoke, sleep_fn)
        except KeyboardInterrupt:
            summary = {"recovery_status": "ABORTED", "abort_reason": "operator_interrupt", "infrastructure_recovered": True, "out_of_original_order": True, "recovery_invocation_at_utc": invoked, "recovery_completion_at_utc": _utc_now()}
            (output_dir / "recovery_summary.json").write_bytes(_canonical_json(summary)); return summary
        response = delivery["result"]
        if response is None:
            run = {**entry, "validation_status": "provider_error", "provider_error": f"{type(delivery['last_error']).__name__}: {delivery['last_error']}", "raw_model_response": "", "parsed_candidate_response": None, "delivery_attempts_used": delivery["attempts_used"]}
            status = "INCOMPLETE / INFRASTRUCTURE"
        else:
            visible = _read_json(output_dir / CANDIDATE_FILENAME)
            try:
                parsed = parse_discovery_response(response.text, [x["id"] for x in visible["decisions"]]); validation, error = "valid", None
            except OutputValidationError as exc:
                parsed, validation, error = None, "invalid", str(exc)
            run = {**entry, "validation_status": validation, "validation_error": error, "provider_error": None, "raw_model_response": response.text, "parsed_candidate_response": parsed, "delivery_attempts_used": delivery["attempts_used"], "model_name": response.model_name or MODEL_ID, "model_version": response.model_version, "latency_ms": response.latency_ms, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens}
            status = "RECOVERED / VALID" if validation == "valid" else "FAIL / MODEL OUTPUT"
            if validation == "valid":
                evaluation = {"original_global_execution_index": entry["original_global_execution_index"], "scenario_id": entry["scenario_id"], "condition_id": entry["condition_id"], "repetition_id": entry["repetition_id"], "evaluation": asdict(evaluate_discovery(load_scenario(entry["scenario_id"]), parsed))}
                (output_dir / "recovery_evaluation.json").write_bytes(_canonical_json(evaluation))
        completed = _utc_now(); run.update({"recovery_invocation_at_utc": invoked, "recovery_completion_at_utc": completed})
        (output_dir / "recovery_run.json").write_bytes(_canonical_json(run))
        summary = {"recovery_status": status, "scientific_observations_planned": 1, "scientific_observations_completed": int(run["validation_status"] in {"valid", "invalid"}), "provider_failures": int(run["validation_status"] == "provider_error"), "valid_outputs": int(run["validation_status"] == "valid"), "invalid_outputs": int(run["validation_status"] == "invalid"), "evaluations_persisted": int((output_dir / "recovery_evaluation.json").exists()), "original_experiment_status": manifest["original_experiment_status"], "contains_infrastructure_recovered_observation": run["validation_status"] == "valid", "out_of_original_order_recovery_count": int(run["validation_status"] == "valid"), "infrastructure_recovered": True, "out_of_original_order": True, "original_global_execution_index": entry["original_global_execution_index"], "recovery_invocation_at_utc": invoked, "recovery_completion_at_utc": completed}
        (output_dir / "recovery_summary.json").write_bytes(_canonical_json(summary)); return summary
    finally:
        if hasattr(adapter, "close"):
            adapter.close()


def recovered_view_metadata(manifest: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    if summary.get("recovery_status") != "RECOVERED / VALID":
        raise RecoveryError("a recovered screening view requires one valid recovered observation")
    return {"view_type": "round-b-v0.2-recovered-screening-view", "contains_infrastructure_recovered_observation": True, "out_of_original_order_recovery_count": 1, "original_experiment_status": "INCOMPLETE / INFRASTRUCTURE", "original_global_execution_index": manifest["eligible_slot"]["original_global_execution_index"], "recovery_protocol_sha256": manifest["recovery_protocol_sha256"], "sensitivity_reporting_required": True, "sensitivity_evaluated": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Round B v0.2 infrastructure recovery")
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true"); action.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = prepare_recovery(args.original_dir, args.output_dir) if args.prepare else execute_recovery(args.original_dir, args.output_dir)
    print(json.dumps({"status": "PREPARED", "execute_eligible": result["execute_eligible"]} if args.prepare else result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
