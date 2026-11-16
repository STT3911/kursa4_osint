from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import joblib
import sklearn
from sklearn.linear_model import LogisticRegression

import ai_classifier
import identity_matcher
from model_artifacts import ModelArtifactError, load_sklearn_artifact


class ModelArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "models"
        self.root.mkdir()
        self.path = self.root / "classifier.joblib"

    def tearDown(self):
        self.temp.cleanup()

    def write_foreign_estimator(self, kind="classifier"):
        # Simulate the sklearn version stored in a real estimator's pickle state.
        with patch("sklearn.base.__version__", "0.0.0"):
            joblib.dump({kind: LogisticRegression(), "feature_schema_version": 2,
                         "feature_names": identity_matcher.FEATURE_NAMES}, self.path)

    def test_current_version_estimator_loads(self):
        model = LogisticRegression()
        joblib.dump({"classifier": model, "sklearn_version": sklearn.__version__}, self.path)
        artifact = load_sklearn_artifact(self.path, self.root)
        self.assertIsInstance(artifact["classifier"], LogisticRegression)

    def test_foreign_estimator_is_rejected_without_printing_warning(self):
        self.write_foreign_estimator()
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always")
            with self.assertRaisesRegex(ModelArtifactError, "0.0.0"):
                load_sklearn_artifact(self.path, self.root)
        self.assertEqual(emitted, [])

    def test_explicit_foreign_runtime_metadata_is_rejected(self):
        joblib.dump({"sklearn_version": "0.0.0"}, self.path)
        with self.assertRaisesRegex(ModelArtifactError, "0.0.0"):
            load_sklearn_artifact(self.path, self.root)

    def test_corrupt_pickle_has_actionable_failure(self):
        self.path.write_bytes(b"this is not a joblib artifact")
        with self.assertRaisesRegex(ModelArtifactError, self.path.name):
            load_sklearn_artifact(self.path, self.root)

    def test_path_outside_models_is_never_unpickled(self):
        outside = Path(self.temp.name) / "outside.joblib"
        joblib.dump({}, outside)
        with patch("joblib.load") as loader:
            with self.assertRaises(ModelArtifactError):
                load_sklearn_artifact(outside, self.root)
            loader.assert_not_called()

    def test_profile_classifier_keeps_rules_on_version_mismatch(self):
        self.write_foreign_estimator()
        with patch.object(ai_classifier, "MODELS_DIR", self.root):
            classifier = ai_classifier.ProfileClassifier(classifier_path=self.path)
        self.assertFalse(classifier.is_trained)
        self.assertIn("0.0.0", classifier.disabled_reason)
        result = classifier.classify({"bio": "python backend"}, allow_embeddings=False)
        self.assertEqual(result["source"], "rules")

    def test_profile_classifier_keeps_rules_on_corrupt_file(self):
        self.path.write_bytes(b"broken")
        with patch.object(ai_classifier, "MODELS_DIR", self.root):
            classifier = ai_classifier.ProfileClassifier(classifier_path=self.path)
        self.assertFalse(classifier.is_trained)
        self.assertTrue(classifier.disabled_reason)

    def test_identity_matcher_keeps_rules_on_version_mismatch(self):
        self.write_foreign_estimator(kind="model")
        with patch.object(identity_matcher, "MODELS_DIR", self.root):
            matcher = identity_matcher.IdentityMatcher(
                model_path=self.path, report_path=self.root / "missing.json")
        self.assertFalse(matcher.is_trained)
        self.assertIn("0.0.0", matcher.disabled_reason)
        result = matcher.match({"username": "sample"}, {"profile_url": "https://github.com/sample"})
        self.assertEqual(result["identity_source"], "rules")

    def test_compatible_identity_model_is_still_used(self):
        model = LogisticRegression().fit(
            [[0.0] * len(identity_matcher.FEATURE_NAMES),
             [1.0] * len(identity_matcher.FEATURE_NAMES)], [0, 1])
        joblib.dump({"model": model, "feature_schema_version": 2,
                     "feature_names": identity_matcher.FEATURE_NAMES,
                     "sklearn_version": sklearn.__version__, "decision_threshold": .5}, self.path)
        with patch.object(identity_matcher, "MODELS_DIR", self.root):
            matcher = identity_matcher.IdentityMatcher(
                model_path=self.path, report_path=self.root / "missing.json")
        self.assertTrue(matcher.is_trained)
        result = matcher.match({"username": "sample"}, {"profile_url": "https://github.com/sample"})
        self.assertEqual(result["identity_source"], "trained")

    def test_invalid_report_disables_identity_model_without_crashing(self):
        joblib.dump({}, self.path)
        report = self.root / "report.json"
        report.write_text("{bad json", encoding="utf-8")
        with patch.object(identity_matcher, "MODELS_DIR", self.root):
            matcher = identity_matcher.IdentityMatcher(model_path=self.path, report_path=report)
        self.assertFalse(matcher.is_trained)
        self.assertIn("invalid training report", matcher.disabled_reason)

    def test_absent_classifier_does_not_report_version_error(self):
        classifier = ai_classifier.ProfileClassifier(classifier_path=self.path)
        self.assertFalse(classifier.is_trained)
        self.assertEqual(classifier.disabled_reason, "")


if __name__ == "__main__":
    unittest.main()
