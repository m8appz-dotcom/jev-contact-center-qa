"""Public UI packaging must retain native scoring and the selected original design."""

import json
from pathlib import Path
import tempfile
import unittest

from tools.build_recorded_review import ROOT, build, recorded_snapshot


class RecordedReviewTests(unittest.TestCase):
    def test_native_critical_failure_and_uncertainty_are_not_overridden_by_score(self):
        results = recorded_snapshot()["assessments"]
        self.assertEqual(set(results), {"MINI-1", "MINI-2", "MINI-3"})
        first = results["MINI-1"]
        self.assertEqual((first["score"], first["outcome"]), (80, "Failed"))
        identity = next(c for c in first["criteria"] if c["label"] == "Identity verification")
        self.assertTrue(identity["critical"])
        self.assertFalse(identity["meets"])
        third = results["MINI-3"]
        self.assertEqual((third["score"], third["outcome"]), (90, "Passed"))
        self.assertTrue(third["needsReview"])
        for result in results.values():
            self.assertEqual(len(result["criteria"]), 8)
            self.assertEqual(result["model"], "jev-1.14.0")

    def test_public_package_preserves_styles_and_private_source_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            build(destination)
            for name in ("base.css", "products.css", "ui.css", "core.js"):
                self.assertEqual(
                    (destination / "review" / name).read_bytes(),
                    (ROOT / "demo/public" / name).read_bytes(),
                )
            self.assertIn('data-assessment-mode="recorded"', (destination / "review/index.html").read_text())
            self.assertNotIn("data-assessment-mode", (ROOT / "demo/public/index.html").read_text())
            snapshot = json.loads((destination / "review/recorded-assessments.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot, recorded_snapshot())
            self.assertEqual(
                (destination / "results.csv").read_bytes(),
                (ROOT / "docs/examples/live-english/results.csv").read_bytes(),
            )
            self.assertFalse((destination / ".env").exists())


if __name__ == "__main__":
    unittest.main()
