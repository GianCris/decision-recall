import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from google.auth.exceptions import DefaultCredentialsError
from google.genai import errors as genai_errors

from dr_baselines import ExperimentConfig
from dr_baselines.output import DISCOVERY_RESPONSE_JSON_SCHEMA
from dr_baselines.google_adapter import (
    API_VERSION, LOCATION, MODEL_ID, PROJECT_ID,
    GeminiAuthenticationError, GeminiVertexAdapter,
)


class GoogleAdapterTests(unittest.TestCase):
    def test_client_uses_enterprise_vertex_target_and_adc(self):
        credentials = object()
        fake_client = Mock()
        with patch("dr_baselines.google_adapter.google.auth.default", return_value=(credentials, "adc-project")) as auth_default, patch("dr_baselines.google_adapter.genai.Client", return_value=fake_client) as client_type:
            adapter = GeminiVertexAdapter()
            self.assertIs(adapter.client, fake_client)
        auth_default.assert_called_once()
        kwargs = client_type.call_args.kwargs
        self.assertEqual(kwargs["enterprise"], True)
        self.assertIs(kwargs["credentials"], credentials)
        self.assertEqual(kwargs["project"], PROJECT_ID)
        self.assertEqual(kwargs["location"], LOCATION)
        self.assertEqual(kwargs["http_options"].api_version, API_VERSION)
        self.assertNotIn("api_key", kwargs)

    def test_generate_is_one_non_streaming_call_without_generation_config(self):
        usage = SimpleNamespace(prompt_token_count=123, candidates_token_count=45)
        response = SimpleNamespace(text='{"decisions":[]}', model_version="gemini-3.7-flash-001", usage_metadata=usage)
        client = Mock()
        client.models.generate_content.return_value = response
        result = GeminiVertexAdapter(client).generate("prompt", ExperimentConfig(model_name=MODEL_ID))
        client.models.generate_content.assert_called_once_with(model=MODEL_ID, contents="prompt")
        self.assertEqual(result.model_name, MODEL_ID)
        self.assertEqual(result.model_version, "gemini-3.7-flash-001")
        self.assertEqual(result.input_tokens, 123)
        self.assertEqual(result.output_tokens, 45)
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_structured_generate_uses_native_json_schema_only(self):
        response = SimpleNamespace(text='{"decisions":[]}', model_version=None, usage_metadata=None)
        client = Mock()
        client.models.generate_content.return_value = response
        GeminiVertexAdapter(client).generate(
            "prompt",
            ExperimentConfig(model_name=MODEL_ID),
            response_schema=DISCOVERY_RESPONSE_JSON_SCHEMA,
        )
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], MODEL_ID)
        self.assertEqual(request["contents"], "prompt")
        provider_config = request["config"]
        self.assertEqual(provider_config.response_mime_type, "application/json")
        self.assertEqual(provider_config.response_json_schema, DISCOVERY_RESPONSE_JSON_SCHEMA)
        for field in (
            "temperature", "top_p", "top_k", "thinking_config", "seed",
            "presence_penalty", "frequency_penalty", "stop_sequences", "tools",
            "max_output_tokens",
        ):
            self.assertIsNone(getattr(provider_config, field))

    def test_missing_adc_fails_closed(self):
        with patch("dr_baselines.google_adapter.google.auth.default", side_effect=DefaultCredentialsError("missing")), patch("dr_baselines.google_adapter.genai.Client") as client_type:
            with self.assertRaisesRegex(GeminiAuthenticationError, "Application Default Credentials"):
                _ = GeminiVertexAdapter().client
            client_type.assert_not_called()

    def test_provider_auth_rejection_is_clear_and_not_retried(self):
        client = Mock()
        client.models.generate_content.side_effect = genai_errors.ClientError(401, {"error": {"message": "unauthorized", "status": "UNAUTHENTICATED"}})
        with self.assertRaisesRegex(GeminiAuthenticationError, "rejected"):
            GeminiVertexAdapter(client).generate("prompt", ExperimentConfig(model_name=MODEL_ID))
        client.models.generate_content.assert_called_once()

    def test_mismatched_model_config_is_rejected_before_call(self):
        client = Mock()
        with self.assertRaises(ValueError):
            GeminiVertexAdapter(client).generate("prompt", ExperimentConfig(model_name="another-model"))
        client.models.generate_content.assert_not_called()
