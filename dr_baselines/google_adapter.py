from __future__ import annotations

from time import perf_counter
from typing import Any

import google.auth
from google import genai
from google.auth.exceptions import GoogleAuthError
from google.genai import types
from google.genai import errors as genai_errors

from .config import ExperimentConfig
from .models import ModelResponse

PROJECT_ID = "decision-recall-hackathon"
LOCATION = "global"
MODEL_ID = "gemini-3.7-flash"
API_VERSION = "v1"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class GeminiAuthenticationError(RuntimeError):
    pass


class GeminiVertexAdapter:
    """Synchronous, non-streaming Google Cloud Agent Platform adapter using ADC."""

    identifier = "google-genai-vertex-gemini-3.7-flash-v0.1"

    def __init__(self, client: Any | None = None):
        self._client = client

    def _create_client(self) -> Any:
        try:
            credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
        except GoogleAuthError as exc:
            raise GeminiAuthenticationError(
                "Application Default Credentials are unavailable or invalid. "
                "Run 'gcloud auth application-default login' and configure project access."
            ) from exc
        return genai.Client(
            enterprise=True,
            credentials=credentials,
            project=PROJECT_ID,
            location=LOCATION,
            http_options=types.HttpOptions(api_version=API_VERSION),
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def generate(self, prompt: str, config: ExperimentConfig) -> ModelResponse:
        if config.model_name not in {None, MODEL_ID}:
            raise ValueError(f"adapter requires model_name={MODEL_ID!r}")
        started = perf_counter()
        try:
            response = self.client.models.generate_content(model=MODEL_ID, contents=prompt)
        except GoogleAuthError as exc:
            raise GeminiAuthenticationError("Application Default Credentials failed during the provider request.") from exc
        except genai_errors.ClientError as exc:
            if exc.code in {401, 403}:
                raise GeminiAuthenticationError(
                    "Application Default Credentials were rejected or lack access to the configured project."
                ) from exc
            raise
        latency_ms = (perf_counter() - started) * 1000
        usage = getattr(response, "usage_metadata", None)
        return ModelResponse(
            text=getattr(response, "text", None) or "",
            model_name=MODEL_ID,
            model_version=getattr(response, "model_version", None),
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
        )

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()
