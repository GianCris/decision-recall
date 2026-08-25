from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from .golden_loop import run_golden_decision
from .presentation import build_decision_threads_presentation


_DIST_ROOT = Path(
    os.environ.get("DECISION_THREADS_DIST", "apps/decision-threads/dist")
).resolve()


def build_runtime_presentation() -> dict[str, object]:
    """Run the deterministic golden loop and return its judge-facing projection."""

    result = run_golden_decision()
    presentation = build_decision_threads_presentation(result)
    return asdict(presentation)


class DecisionRecallHandler(BaseHTTPRequestHandler):
    server_version = "DecisionRecallCloudRun/0.2"

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

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path

        # Cloud Run reserves some paths ending in "z". /health is the public
        # deployment-proof route; /healthz remains a harmless local alias.
        if path in {"/health", "/healthz"}:
            self._send_json(
                {
                    "status": "ok",
                    "service": "decision-recall",
                    "runtime": "cloud-run-live",
                }
            )
            return

        if path == "/api/presentation":
            try:
                payload = build_runtime_presentation()
            except Exception as exc:  # fail visibly rather than fabricating UI state
                self._send_json(
                    {
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(payload)
            return

        self._send_static(path)

    def log_message(self, format: str, *args: object) -> None:
        print(f"cloudrun http: {format % args}")


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DecisionRecallHandler)
    print(f"Decision Recall Cloud Run server listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
