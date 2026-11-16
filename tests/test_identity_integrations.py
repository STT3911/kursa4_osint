from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from identity_matcher import build_identity_features
from qwen_identity import record, validate_response, QwenIdentityReviewer
from spiderfoot_integration import parse_spiderfoot_json, run_spiderfoot, canonical_url
from local_identity_review import (
    fetch_public_account, process_qwen_review, load_reviews, _signature, _discovery_signature,
    _ensure_table,
)


def event(data, source="target_user", event_type="Account on External Site"):
    return {"module": "sfp_accounts", "type": event_type, "source": source, "data": data}


def output(verdict="likely_same_person", field="bio", left="project-alpha", right="project-alpha"):
    return json.dumps({"verdict": verdict, "matches": [
        {"left_field": field, "right_field": field, "left_quote": left,
         "right_quote": right, "reason": "The same named project."}
    ], "contradictions": []})


class SpiderFootTests(unittest.TestCase):
    def test_actual_cli_labels_markup_removed_deduplicated(self):
        events = [event("GitHub (Category: coding)\nhttps://github.com/target_user/"),
                  event("GitHub (Category: coding)\n<SFURL>https://github.com/target_user</SFURL>")]
        accounts = parse_spiderfoot_json(json.dumps(events), "target_user")
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["username"], "")
        self.assertEqual(accounts[0]["queried_username"], "target_user")

    def test_other_seed_and_non_account_events_are_rejected(self):
        events = [event("GitHub\nhttps://github.com/alice", source="alice"),
                  event("GitHub\nhttps://github.com/target_user", event_type="USERNAME")]
        self.assertEqual(parse_spiderfoot_json(json.dumps(events), "target_user"), [])

    def test_malformed_output_is_not_silently_successful(self):
        for text in ("log\n[]", '[{"data":', "{}", ""):
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                parse_spiderfoot_json(text, "target_user")

    def test_scan_failure_preserves_failure(self):
        with patch("spiderfoot_integration._settings", return_value=(Path("/tmp/sf.py"), "python")), \
             patch("spiderfoot_integration.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 1, "[]", "failed")):
            with self.assertRaises(RuntimeError):
                run_spiderfoot("target_user")

    def test_timeout_propagates_and_no_shell_is_used(self):
        with patch("spiderfoot_integration._settings", return_value=(Path("/tmp/sf.py"), "python")), \
             patch("spiderfoot_integration.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["python"], 1)) as runner:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_spiderfoot("target_user", 1)
            self.assertIsInstance(runner.call_args.args[0], list)
            self.assertNotIn("shell", runner.call_args.kwargs)

    def test_dotted_nickname_is_passed_as_username_not_domain(self):
        with patch("spiderfoot_integration._settings", return_value=(Path("/tmp/sf.py"), "python")), \
             patch("spiderfoot_integration.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 0, "[]", "")) as runner:
            self.assertEqual(run_spiderfoot("alice.dev"), [])
            args = runner.call_args.args[0]
            self.assertEqual(args[args.index("-s") + 1], '"alice.dev"')

    def test_command_like_nickname_is_rejected(self):
        with self.assertRaises(ValueError):
            run_spiderfoot("name; echo secret")


class QwenTests(unittest.TestCase):
    def setUp(self):
        self.left = {"username": "target_user", "name": "", "bio": "project-alpha developer", "links": ""}
        self.right = {"username": "another", "name": "", "bio": "project-alpha contributor", "links": ""}

    def test_real_quoted_evidence_is_accepted_without_probability(self):
        result = validate_response(output(), self.left, self.right)
        self.assertEqual(result["verdict"], "likely_same_person")
        self.assertNotIn("probability", result)

    def test_hallucinated_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_response(output(left="invented project"), self.left, self.right)

    def test_username_alone_abstains(self):
        result = validate_response(output(field="username", left="target_user", right="another"),
                                   self.left, self.right)
        self.assertEqual(result["verdict"], "insufficient_evidence")

    def test_contradictions_are_required_for_negative_verdict(self):
        raw = json.dumps({"verdict": "unlikely_same_person", "matches": [], "contradictions": []})
        self.assertEqual(validate_response(raw, self.left, self.right)["verdict"],
                         "insufficient_evidence")

    def test_model_cannot_add_confidence(self):
        obj = json.loads(output())
        obj["probability"] = .99
        with self.assertRaises(ValueError):
            validate_response(json.dumps(obj), self.left, self.right)

    def test_search_seed_and_platform_are_excluded(self):
        result = record({"username": "searched", "queried_username": "searched",
                         "site_name": "java programming", "profile_url": "https://example.org/searched"})
        self.assertEqual(result, {"username": "", "name": "", "bio": "", "links": ""})

    def test_no_external_evidence_never_loads_model(self):
        reviewer = QwenIdentityReviewer()
        with patch.object(reviewer, "_load") as loader:
            result = reviewer.review({"username": "target_user"}, {"username": "target_user"})
            loader.assert_not_called()
        self.assertEqual(result["verdict"], "insufficient_evidence")

    def test_echoed_search_username_is_not_identity_evidence(self):
        features = build_identity_features(
            {"username": "target_user", "bio": "java"},
            {"username": "target_user", "source": "sherlock",
             "site_name": "java programming", "profile_url": "https://github.com/unrelated"},
        )
        self.assertEqual(features["username_exact"], 0)
        self.assertEqual(features["bio_url_overlap"], 0)

    def test_arbitrary_urls_never_make_requests(self):
        for url in ("http://127.0.0.1/admin", "https://github.com.attacker.org/alice",
                    "https://github.com/alice?x=1", "https://github.com/alice/repo"):
            with patch("local_identity_review.build_opener") as opener:
                self.assertEqual(fetch_public_account(url)["fetch_status"], "unsupported")
                opener.assert_not_called()


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = (database.ACTIVE_DB_PATH, database.ACTIVE_DB_URI, database.DB_READY)
        database.ACTIVE_DB_PATH = Path(self.temp.name) / "test.db"
        database.ACTIVE_DB_URI = False
        database.DB_READY = True
        with database.get_connection() as conn:
            _ensure_table(conn)

    def tearDown(self):
        database.ACTIVE_DB_PATH, database.ACTIVE_DB_URI, database.DB_READY = self.previous
        self.temp.cleanup()

    def test_review_is_invalidated_when_profile_changes(self):
        from datetime import datetime, timezone
        profile = {"username": "target_user", "bio": "project-alpha"}
        account = {"profile_url": "https://github.com/target_user", "checked_at": "2026-01-01"}
        review = {"verdict": "insufficient_evidence", "matches": [], "contradictions": []}
        with database.get_connection() as conn:
            conn.execute("INSERT INTO qwen_identity_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (1, canonical_url(account["profile_url"]), _signature(profile),
                          _discovery_signature(account), QwenIdentityReviewer().model_id, 1,
                          json.dumps(review), datetime.now(timezone.utc).isoformat()))
            conn.commit()
        self.assertTrue(load_reviews(1, profile, [account]))
        self.assertFalse(load_reviews(1, dict(profile, bio="different"), [account]))
        self.assertFalse(load_reviews(1, profile, [dict(account, checked_at="new")]))

    def test_duplicate_discoveries_produce_one_review(self):
        profile = {"username": "target_user", "bio": "project-alpha"}
        account = {"profile_url": "https://github.com/target_user", "checked_at": "now"}
        with patch("database.get_profile_card", return_value={
            "profile": profile, "social_accounts": [account, dict(account, source="other")]
        }), patch("local_identity_review.fetch_public_account", return_value={
            "fetch_status": "unsupported"
        }) as fetch:
            result = process_qwen_review(1)
        self.assertEqual(result["found_count"], 1)
        fetch.assert_called_once()

    def test_fetch_errors_do_not_become_negative_matches(self):
        with patch("database.get_profile_card", return_value={
            "profile": {"username": "target_user"},
            "social_accounts": [{"profile_url": "https://github.com/target_user"}]
        }), patch("local_identity_review.fetch_public_account", side_effect=OSError("network failed")):
            result = process_qwen_review(1)
        self.assertEqual(result["status"], "error")
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM qwen_identity_reviews").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
