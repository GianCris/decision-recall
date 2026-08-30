from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from math import isfinite
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..domain import CompositionValue, HistoricalKnowledgeState, NumericObservation, ProvenanceType
from ..temporal import (
    LedgerEntryKind,
    RawWorldEvidence,
    TemporalIntegrityError,
    TemporalReference,
    WorldEventAuthorizationRecord,
    source_hash,
)
from .declaration import CaptureAnswer, capture_question_hash
from .golden_loop import (
    T0,
    complete_golden_capture,
    prepare_golden_capture,
    reevaluate_golden_decision,
    run_golden_decision,
)
from .presentation import build_decision_threads_presentation
from .case_api import CaseBindingMismatch, UnknownCase, registered_case_api


_DIST_ROOT = Path(
    os.environ.get("DECISION_THREADS_DIST", "apps/decision-threads/dist")
).resolve()
_MAX_CAPTURE_BODY_BYTES = 4096
_MAX_REEVALUATE_BODY_BYTES = 12288
_CAPTURE_KEYS = frozenset({"capture_session_id", "gap_id", "question_hash", "answer"})
_REEVALUATE_KEYS = frozenset({"decision_id", "capture", "world_time", "evidence"})
_EVIDENCE_KEYS = frozenset(
    {"evidence_id", "metric_key", "value", "unit", "window_days", "observed_at", "source"}
)
_REQUIRED_METRICS = frozenset({"apex_on_time_rate", "beacon_reactivation_days"})
_SUPPLIED_SOURCE = "supplied_current_record"


class CaptureBindingMismatch(ValueError):
    """The browser response does not match the server-reconstructed capture."""


class ReevaluationConflict(ValueError):
    """The supplied temporal envelope conflicts with the narrow live contract."""


def build_runtime_presentation() -> dict[str, object]:
    """Run the deterministic winner loop and return its judge-facing projection."""

    result = run_golden_decision()
    presentation = build_decision_threads_presentation(result)
    return asdict(presentation)


def _capture_preparation_projection(preparation) -> dict[str, object]:
    """Project authoritative preparation without completing capture."""

    if len(preparation.critical_gaps) != 1:
        raise RuntimeError("winner capture preparation must expose exactly one critical gap")

    gap = preparation.critical_gaps[0]
    relation = preparation.draft_contract.relation(gap.slot_id)
    return {
        "decision_id": preparation.draft_contract.id,
        "capture_session_id": preparation.session.assignment.session_id,
        "gap_id": gap.slot_id,
        "question": gap.question,
        "question_hash": capture_question_hash(gap.question),
        "profile_hash": preparation.session.assignment.profile_hash,
        "knowledge_state": relation.knowledge_state.value,
    }


def build_capture_preparation() -> dict[str, object]:
    """Return authoritative pre-capture state without running the YES completion."""

    return _capture_preparation_projection(prepare_golden_capture())


def _validate_capture_payload(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("capture payload must be a JSON object")
    if frozenset(payload) != _CAPTURE_KEYS:
        raise ValueError("capture payload keys do not match the winner-slice schema")
    if any(not isinstance(payload[key], str) or not payload[key].strip() for key in _CAPTURE_KEYS):
        raise ValueError("capture payload values must be non-empty strings")
    if payload["answer"] != CaptureAnswer.YES.value:
        raise ValueError("winner-slice capture accepts only answer=yes")
    return {key: payload[key] for key in _CAPTURE_KEYS}


def _verify_capture_binding(request: dict[str, str], authoritative: dict[str, object]) -> None:
    expected = {
        "capture_session_id": authoritative["capture_session_id"],
        "gap_id": authoritative["gap_id"],
        "question_hash": authoritative["question_hash"],
    }
    mismatches = tuple(key for key, value in expected.items() if request[key] != value)
    if mismatches:
        raise CaptureBindingMismatch(
            "capture response does not match authoritative issued state: " + ", ".join(mismatches)
        )


def complete_verified_capture(payload: object) -> dict[str, object]:
    """Verify browser binding against reconstructed T0 state, then allow YES completion.

    This is intentionally not a stateful web session. The server reconstructs
    the authoritative issued capture on every request. The HTTP response is
    verified against that state before the frozen deterministic winner path is
    allowed to establish R2.
    """

    request = _validate_capture_payload(payload)
    preparation = prepare_golden_capture()
    authoritative = _capture_preparation_projection(preparation)
    _verify_capture_binding(request, authoritative)

    completion = complete_golden_capture(preparation, capture_answer=CaptureAnswer.YES)
    r2 = completion.materialized_contract.relation(request["gap_id"])
    c1 = completion.materialized_contract.composition("C1")
    if r2.knowledge_state is not HistoricalKnowledgeState.ESTABLISHED:
        raise RuntimeError("verified winner completion did not establish R2")
    if c1.value is not CompositionValue.NOT_DURABLY_RECORDED:
        raise RuntimeError("verified winner completion must leave C1 unresolved")
    forbidden = {
        LedgerEntryKind.RAW_WORLD_EVIDENCE,
        LedgerEntryKind.WORLD_EVENT_AUTHORIZATION,
        LedgerEntryKind.EVALUATION,
    }
    if any(entry.kind in forbidden for entry in completion.ledger.entries_as_of(completion.ledger.head_seq)):
        raise RuntimeError("live capture response cannot contain later-world state")

    return {
        "capture_validation": {
            "status": "accepted",
            "capture_session_id": request["capture_session_id"],
            "gap_id": request["gap_id"],
            "question_hash": request["question_hash"],
            "answer": request["answer"],
            "completion": "allowed",
        },
        "capture": {
            "decision_id": completion.commit.decision_id,
            "relation_id": r2.id,
            "knowledge_state": r2.knowledge_state.value,
            "commit_id": completion.commit.commit_id,
            "commit_batch_seq": completion.commit.commit_cutoff_seq,
        },
        "future_evaluation_status": "not_requested",
    }


def _parse_aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError(f"{field} must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _validate_reevaluation_payload(
    payload: object,
) -> tuple[dict[str, str], datetime, tuple[RawWorldEvidence, ...]]:
    if not isinstance(payload, dict):
        raise ValueError("reevaluation payload must be a JSON object")
    if frozenset(payload) != _REEVALUATE_KEYS:
        raise ValueError("reevaluation payload keys do not match the winner-slice schema")
    if payload["decision_id"] != "D-104":
        raise ValueError("reevaluation decision_id must be D-104")

    capture = _validate_capture_payload(payload["capture"])
    world_time = _parse_aware_datetime(payload["world_time"], "world_time")
    if world_time <= T0:
        raise TemporalIntegrityError("world_time must be later than T0")

    evidence_payload = payload["evidence"]
    if not isinstance(evidence_payload, list) or len(evidence_payload) != 2:
        raise ValueError("reevaluation evidence must contain exactly two records")

    evidence_ids: set[str] = set()
    metric_keys: set[str] = set()
    records: list[RawWorldEvidence] = []
    for index, item in enumerate(evidence_payload):
        if not isinstance(item, dict) or frozenset(item) != _EVIDENCE_KEYS:
            raise ValueError(f"evidence[{index}] keys do not match the winner-slice schema")

        for field in ("evidence_id", "metric_key", "unit", "source"):
            value = item[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"evidence[{index}].{field} must be a non-empty bounded string")
        evidence_id = item["evidence_id"]
        metric_key = item["metric_key"]
        if evidence_id in evidence_ids:
            raise ReevaluationConflict("reevaluation evidence IDs must be unique")
        if metric_key in metric_keys:
            raise ReevaluationConflict("reevaluation metric keys must be unique")
        evidence_ids.add(evidence_id)
        metric_keys.add(metric_key)

        value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"evidence[{index}].value must be a finite JSON number")
        window_days = item["window_days"]
        if window_days is not None and (
            isinstance(window_days, bool) or not isinstance(window_days, int)
        ):
            raise ValueError(f"evidence[{index}].window_days must be an integer or null")
        if item["source"] != _SUPPLIED_SOURCE:
            raise ValueError("evidence source is not allowed by the winner-slice transport contract")

        observed_at = _parse_aware_datetime(item["observed_at"], f"evidence[{index}].observed_at")
        if observed_at > world_time:
            raise TemporalIntegrityError("world evidence cannot be effective after world_time")
        if observed_at <= T0:
            raise TemporalIntegrityError("world evidence must be later than T0")
        if metric_key == "apex_on_time_rate" and window_days != 30:
            raise TemporalIntegrityError("apex_on_time_rate requires a 30-day window")
        if metric_key == "beacon_reactivation_days" and window_days is not None:
            raise TemporalIntegrityError("beacon_reactivation_days does not accept a window")

        content = f"{metric_key}={value} {item['unit']}"
        records.append(
            RawWorldEvidence(
                id=evidence_id,
                content=content,
                source_id=f"supplied-current-record:{evidence_id}",
                source_span="supplied current record",
                source_content_hash=source_hash(content),
                provenance_type=ProvenanceType.CONTEMPORANEOUS_RECORD,
                temporal_reference=TemporalReference.point(observed_at),
                observations=(
                    NumericObservation(
                        metric_key=metric_key,
                        value=float(value),
                        unit=item["unit"],
                        window_days=window_days,
                    ),
                ),
            )
        )

    if metric_keys != _REQUIRED_METRICS:
        raise TemporalIntegrityError("reevaluation evidence does not contain the required D-104 metrics")
    return capture, world_time, tuple(records)


def complete_verified_reevaluation(payload: object) -> dict[str, object]:
    """Reconstruct verified T0, then authorize and replay supplied later evidence."""

    capture, world_time, records = _validate_reevaluation_payload(payload)
    preparation = prepare_golden_capture()
    authoritative = _capture_preparation_projection(preparation)
    _verify_capture_binding(capture, authoritative)
    completion = complete_golden_capture(preparation, capture_answer=CaptureAnswer.YES)
    reevaluation = reevaluate_golden_decision(
        completion,
        later_world_evidence=records,
        world_time=world_time,
    )

    authorizations = {
        entry.payload.raw_evidence_id: entry.payload
        for entry in completion.ledger.entries_as_of(completion.ledger.head_seq)
        if entry.kind is LedgerEntryKind.WORLD_EVENT_AUTHORIZATION
        and isinstance(entry.payload, WorldEventAuthorizationRecord)
    }
    result = reevaluation.evaluation.canonical_result
    return {
        "status": "reevaluated",
        "decision_id": completion.commit.decision_id,
        "world_time": world_time.isoformat(),
        "accepted_world_events": [
            {
                "evidence_id": record.id,
                "metric_key": record.observations[0].metric_key,
                "authorization_id": authorizations[record.id].id,
            }
            for record in records
        ],
        "current_matches": [
            {"entity_id": entity_id, "state": state}
            for entity_id, state in result.current_matches
        ],
        "safe_reuse_result": result.safe_reuse_result,
        "limiting_requirements": list(result.limiting_requirements),
        "reason_codes": list(result.reason_codes),
        "evaluation_hash": reevaluation.evaluation.result_hash,
        "replay_hash": reevaluation.replayed_result.result_hash(),
    }


class DecisionRecallHandler(BaseHTTPRequestHandler):
    # Optional server-owned dependency injection, never request-selected config.
    case_api = None

    def _handle_cases(self, method: str, path: str) -> None:
        api = self.case_api if self.case_api is not None else registered_case_api()
        parts = path.split("/")

        def reject_route(status, message):
            # Consume a bounded, length-delimited body before an early rejection.
            # Otherwise a headers-first client can race the HTTP/1.0 socket close.
            lengths = self.headers.get_all("Content-Length", [])
            if (method == "POST" and len(lengths) == 1 and len(lengths[0]) <= 20
                    and lengths[0].isdigit() and not self.headers.get("Transfer-Encoding")):
                size = int(lengths[0])
                if 0 < size <= _MAX_REEVALUATE_BODY_BYTES:
                    self.rfile.read(size)
            self._send_json({"status": "error", "message": message}, status)

        if path == "/api/cases":
            if method == "GET":
                self._send_json(api.cases())
            else:
                reject_route(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
            return
        if len(parts) != 5 or not parts[3] or parts[4] not in {"capture-preparation", "capture", "reevaluate"}:
            reject_route(HTTPStatus.NOT_FOUND, "unknown case route")
            return
        decision_id, operation = unquote(parts[3]), parts[4]
        if method != ("GET" if operation == "capture-preparation" else "POST"):
            reject_route(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
            return
        try:
            if method == "GET":
                result = api.preparation(decision_id)
            else:
                if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                    reject_route(HTTPStatus.BAD_REQUEST, "expected length-delimited application/json")
                    return
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1:
                    raise ValueError("one Content-Length is required")
                size = int(lengths[0])
                maximum = _MAX_CAPTURE_BODY_BYTES if operation == "capture" else _MAX_REEVALUATE_BODY_BYTES
                if size <= 0:
                    raise ValueError("request body size is invalid")
                if size > maximum:
                    self._send_json({"status": "error", "message": "request body exceeds the endpoint limit"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return

                def unique_object(pairs):
                    obj = {}
                    for key, value in pairs:
                        if key in obj:
                            raise ValueError("duplicate JSON field")
                        obj[key] = value
                    return obj

                def reject_constant(value):
                    raise ValueError("non-finite JSON number")

                payload = json.loads(self.rfile.read(size).decode("utf-8"),
                                     object_pairs_hook=unique_object, parse_constant=reject_constant)
                result = api.capture(decision_id, payload) if operation == "capture" else api.reevaluate(decision_id, payload)
        except UnknownCase as exc:
            self._send_json({"status": "error", "message": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        except CaseBindingMismatch as exc:
            self._send_json({"status": "error", "message": str(exc)}, HTTPStatus.CONFLICT)
            return
        except TemporalIntegrityError as exc:
            self._send_json({"status": "error", "message": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
            return
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            self._send_json({"status": "error", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception:
            self._send_json({"status": "error", "message": "registered case request failed"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(result)

    server_version = "DecisionRecallCloudRun/0.3"

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, request_path: str) -> None:
        relative = unquote(request_path.lstrip("/")) or "index.html"
        candidate = (_DIST_ROOT / relative).resolve()

        try:
            candidate.relative_to(_DIST_ROOT)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return

        if not candidate.is_file():
            candidate = _DIST_ROOT / "index.html"

        if not candidate.is_file():
            self.send_error(
                HTTPStatus.SERVICE_UNAVAILABLE.value,
                "Decision Threads build is not present in the container",
            )
            return

        body = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Cache-Control",
            "no-cache" if candidate.name == "index.html" else "public, max-age=3600",
        )
        self.end_headers()
        self.wfile.write(body)

    def _method_not_allowed(self) -> None:
        self._send_json({"status": "error", "message": "method not allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path

        if path == "/api/cases" or path.startswith("/api/cases/"):
            self._handle_cases("GET", path)
            return

        if path in {"/health", "/healthz"}:
            self._send_json(
                {
                    "status": "ok",
                    "service": "decision-recall",
                    "runtime": "cloud-run-live",
                }
            )
            return

        if path == "/api/capture-preparation":
            try:
                self._send_json(build_capture_preparation())
            except Exception as exc:
                self._send_json(
                    {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        if path in {"/api/capture", "/api/reevaluate"}:
            self._method_not_allowed()
            return

        if path == "/api/presentation":
            try:
                payload = build_runtime_presentation()
            except Exception as exc:
                self._send_json(
                    {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(payload)
            return

        self._send_static(path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/api/cases" or path.startswith("/api/cases/"):
            self._handle_cases("POST", path)
            return
        if path not in {"/api/capture", "/api/reevaluate"}:
            self._method_not_allowed()
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            self._send_json(
                {"status": "error", "message": "Content-Type must be application/json"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = -1
        maximum = _MAX_CAPTURE_BODY_BYTES if path == "/api/capture" else _MAX_REEVALUATE_BODY_BYTES
        if content_length <= 0:
            self._send_json(
                {"status": "error", "message": "request body size is invalid"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if content_length > maximum:
            self._send_json(
                {"status": "error", "message": "request body exceeds the endpoint limit"},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            result = (
                complete_verified_capture(payload)
                if path == "/api/capture"
                else complete_verified_reevaluation(payload)
            )
        except (CaptureBindingMismatch, ReevaluationConflict) as exc:
            self._send_json(
                {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                HTTPStatus.CONFLICT,
            )
            return
        except TemporalIntegrityError as exc:
            self._send_json(
                {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )
            return
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_json(
                {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as exc:
            self._send_json(
                {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        self._send_json(result)

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        self._method_not_allowed()

    def log_message(self, format: str, *args: object) -> None:
        print(f"cloudrun http: {format % args}")


def handler_for_cases(api):
    """Construct the same HTTP handler with an explicit server-owned case registry."""
    class ConfiguredDecisionRecallHandler(DecisionRecallHandler):
        case_api = api

    return ConfiguredDecisionRecallHandler


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DecisionRecallHandler)
    print(f"Decision Recall Cloud Run server listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
