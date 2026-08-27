from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from tools.export_pc2_judge_projection import ProjectionExportError, build_projection, canonical_bytes


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "pc2-credentialed-release-evidence.json"
PROJECTION = ROOT / "apps" / "decision-threads" / "src" / "pc2-judge-safe-gemini-projection.json"
RAW_SHA = "9D91A20D4C5D16C40C1C2B72AEB0956B929AC116906A5383662C74F29CF9E7E1"


class Pc2JudgeProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.projection = json.loads(PROJECTION.read_text(encoding="utf-8"))

    def test_manifest_and_projection_attest_to_the_same_raw_artifact(self) -> None:
        self.assertEqual(self.manifest["credentialed_artifact"]["sha256"], RAW_SHA)
        self.assertEqual(self.projection["raw_artifact_sha256"], RAW_SHA)
        self.assertFalse(self.manifest["credentialed_artifact"]["raw_artifact_committed"])

    def test_exporter_rejects_an_incorrect_raw_sha_before_parsing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.json"
            raw.write_bytes(b"{}")
            with self.assertRaisesRegex(ProjectionExportError, "SHA-256 mismatch"):
                build_projection(manifest_path=MANIFEST, raw_path=raw)

    def test_projection_has_only_allowlisted_fields(self) -> None:
        self.assertEqual(
            set(self.projection),
            {
                "projection_version",
                "evidence_class",
                "model",
                "producer_head_sha",
                "producer_probe_version",
                "raw_artifact_sha256",
                "source_excerpts",
                "candidates",
            },
        )
        self.assertTrue(all(set(item) == {"source_id", "exact_quote"} for item in self.projection["source_excerpts"]))
        self.assertTrue(
            all(
                set(item) == {"kind", "semantic_key", "source_id", "exact_quote", "boundary_accepted"}
                for item in self.projection["candidates"]
            )
        )

    def test_expected_d104_evidence_is_present_and_r2_is_not_a_gemini_candidate(self) -> None:
        candidates = {item["semantic_key"]: item for item in self.projection["candidates"]}
        self.assertEqual(
            candidates["historical_support:apex_delivery_instability"]["exact_quote"],
            "Apex instability materially influenced the decision.",
        )
        self.assertEqual(candidates["historical_support:apex_delivery_instability"]["kind"], "historical_role")
        self.assertEqual(
            candidates["beacon_reactivation_delay"]["exact_quote"],
            "Beacon requires roughly 10 weeks to reactivate.",
        )
        self.assertEqual(candidates["beacon_reactivation_delay"]["kind"], "fact")
        self.assertTrue(all(item["boundary_accepted"] is True for item in candidates.values()))
        self.assertNotIn("R2", json.dumps(self.projection))

    def test_committed_projection_uses_deterministic_serialization(self) -> None:
        expected = canonical_bytes(self.projection)
        self.assertEqual(PROJECTION.read_bytes(), expected)
        self.assertEqual(sha256(expected).hexdigest(), sha256(canonical_bytes(self.projection)).hexdigest())


if __name__ == "__main__":
    unittest.main()
