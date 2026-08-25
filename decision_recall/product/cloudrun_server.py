from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from .declaration import CaptureAnswer, capture_question_hash
from .golden_loop import prepare_golden_capture, run_golden_decision
from .presentation import build_decision_threads_presentation


_DIST_ROOT = Path(
    os.environ.get("DECISION_THREADS_DIST", "apps/decision-threads/dist")
).resolve()
_MAX_CAPTURE_BODY_BYTES = 4096
_CAPTURE_KEYS = frozenset({"capture_session_id", "gap_id", "question_hash", "answer"})


class CaptureBindingMismatch(ValueError):
    """The browser response does not match the server-reconstructed capture."""


def build_runtime_presentation() -> dict[str, object]:
    """Run the deterministic winner loop and return its judge-facing projection."""

    result = run_golden_decision()
    presentation = build_decision_threads_presentation(result)
    return asdict(presentation)


def build_capture_preparation() -> dict[str, object]:
    """Return authoritative pre-capture state without running the YES completion."""

    preparation = prepare_golden_capture()
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


def complete_verified_capture(payload: object) -> dict[str, object]:
    """Verify browser binding against reconstructed T0 state, then allow YES completion.

    This is intentionally not a stateful web session. The server reconstructs
    the authoritative issued capture on every request. The HTTP response is
    verified against that state before the frozen deterministic winner path is
    allowed to establish R2.
    """

    request = _validate_capture_payload(payload)
    authoritative = build_capture_preparation()

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

    result = run_golden_decision(capture_answer=CaptureAnswer.YES)
    presentation = asdict(build_decision_threads_presentation(result))
    if presentation["capture"]["knowledge_state"] != "established":
        raise RuntimeError("verified winner completion did not establish R2")

    return {
        "capture_validation": {
            "status": "accepted",
            "capture_session_id": request["capture_session_id"],
            "gap_id": request["gap_id"],
            "question_hash": request["question_hash"],
            "answer": request["answer"],
            "completion": "allowed",
        },
        "presentation": presentation,
    }


class DecisionRecallHandler(BaseHTTPRequestHandler):
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

        if path == "/api/capture":
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
        if path != "/api/capture":
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
        if content_length <= 0 or content_length > _MAX_CAPTURE_BODY_BYTES:
            self._send_json(
                {"status": "error", "message": "capture body size is invalid"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            result = complete_verified_capture(payload)
        except CaptureBindingMismatch as exc:
            self._send_json(
                {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                HTTPStatus.CONFLICT,
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


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DecisionRecallHandler)
    print(f"Decision Recall Cloud Run server listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
