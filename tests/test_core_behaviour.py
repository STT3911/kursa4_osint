import unittest
from pathlib import Path

from ai_classifier import infer_profile_class
from identity_matcher import IdentityMatcher
from maigret_integration import parse_maigret_csv, parse_maigret_json


class ProfileClassifierRulesTest(unittest.TestCase):
    def test_backend_profile_detected_by_keywords(self) -> None:
        row = {
            "username": "api_python_dev",
            "bio": "Python backend developer, FastAPI, PostgreSQL",
            "group_name": "python_ru",
        }

        label, confidence, matched_terms = infer_profile_class(row)

        self.assertEqual(label, "backend")
        self.assertGreaterEqual(confidence, 0.69)
        self.assertIn("python", matched_terms)

    def test_designer_profile_detected_by_site_signal(self) -> None:
        row = {
            "username": "ui_case_studio",
            "bio": "Product designer, UI UX, Figma",
            "has_behance": 1,
        }

        label, confidence, matched_terms = infer_profile_class(row)

        self.assertEqual(label, "designer")
        self.assertGreaterEqual(confidence, 0.69)
        self.assertIn("behance", matched_terms)


class IdentityMatcherRulesTest(unittest.TestCase):
    def test_exact_professional_username_is_likely_same_person(self) -> None:
        matcher = IdentityMatcher(model_path=Path("__missing_model__.joblib"))
        profile = {
            "username": "AniCoder",
            "first_name": "Anita",
            "bio": "Python backend developer, GitHub: AniCoder",
        }
        account = {
            "site_name": "GitHub",
            "profile_url": "https://github.com/AniCoder",
            "source": "sherlock",
        }

        result = matcher.match(profile, account)

        self.assertEqual(result["identity_source"], "rules")
        self.assertEqual(result["identity_verdict"], "likely_same_person")
        self.assertGreaterEqual(result["same_person_score"], 0.75)

    def test_weak_username_match_is_unlikely_same_person(self) -> None:
        matcher = IdentityMatcher(model_path=Path("__missing_model__.joblib"))
        profile = {"username": "dev", "first_name": "", "bio": ""}
        account = {
            "site_name": "Instagram",
            "profile_url": "https://instagram.com/random_long_name",
            "source": "sherlock",
        }

        result = matcher.match(profile, account)

        self.assertEqual(result["identity_verdict"], "unlikely_same_person")
        self.assertEqual(result["false_positive_risk"], "high_false_positive_risk")


class MaigretParserTest(unittest.TestCase):
    def test_csv_parser_keeps_only_claimed_profiles(self) -> None:
        csv_path = Path(__file__).resolve().parent / "fixtures" / "maigret_report.csv"

        accounts = parse_maigret_csv(csv_path, "user")

        self.assertEqual(accounts, [{"site_name": "GitHub", "profile_url": "https://github.com/user", "username": "user"}])

    def test_json_parser_accepts_maigret_simple_url_field(self) -> None:
        json_path = Path(__file__).resolve().parent / "fixtures" / "maigret_report_simple.json"

        accounts = parse_maigret_json(json_path, "user")

        self.assertEqual(accounts, [{"site_name": "GitHub", "profile_url": "https://github.com/user", "username": "user"}])


if __name__ == "__main__":
    unittest.main()
