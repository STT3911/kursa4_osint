"""Exercise the real character parser; no model weights, Torch or network required."""
from __future__ import annotations

import json
import unittest

from qwen_identity import (
    PROMPT_VERSION, QwenResponseError, build_response_parser, validate_response,
)
from local_identity_review import PROMPT_VERSION as CACHE_PROMPT_VERSION


def allowed(text: str, *, extra: str = "") -> bool:
    parser = build_response_parser(extra)
    for character in text:
        if character not in parser.get_allowed_characters():
            return False
        parser = parser.add_character(character)
    return parser.can_end()


def answer() -> dict:
    return {"verdict": "insufficient_evidence", "matches": [], "contradictions": []}


class JsonGenerationTests(unittest.TestCase):
    def test_valid_json_allows_field_order_and_whitespace(self):
        self.assertTrue(allowed(json.dumps(answer(), indent=2)))
        self.assertTrue(allowed('{"matches":[],"contradictions":[],"verdict":"insufficient_evidence"}'))

    def test_extra_confidence_field_is_blocked_during_generation(self):
        obj = answer()
        obj["confidence"] = .99
        self.assertFalse(allowed(json.dumps(obj)))

    def test_missing_required_field_is_blocked(self):
        obj = answer()
        del obj["contradictions"]
        self.assertFalse(allowed(json.dumps(obj)))

    def test_markdown_and_commentary_are_blocked(self):
        raw = json.dumps(answer())
        fence = chr(96) * 3
        self.assertFalse(allowed(fence + "json\n" + raw + "\n" + fence))
        self.assertFalse(allowed(raw + " Here is my conclusion."))

    def test_unknown_verdict_is_blocked(self):
        obj = answer()
        obj["verdict"] = "confirmed"
        self.assertFalse(allowed(json.dumps(obj)))

    def test_nested_evidence_schema_is_enforced(self):
        obj = answer()
        obj["matches"] = [{"left_field": "site_name", "left_quote": "GitHub",
                          "right_field": "name", "right_quote": "Alex", "reason": "same"}]
        self.assertFalse(allowed(json.dumps(obj)))

    def test_russian_and_unicode_quotes_remain_available(self):
        obj = answer()
        obj["matches"] = [{"left_field": "bio", "left_quote": "Проект 雪🌳",
                          "right_field": "bio", "right_quote": "Проект 雪🌳",
                          "reason": "Совпадает название проекта"}]
        self.assertTrue(allowed(json.dumps(obj, ensure_ascii=False), extra="Проект 雪🌳"))

    def test_schema_does_not_replace_quote_validation(self):
        obj = answer()
        obj["matches"] = [{"left_field": "bio", "left_quote": "invented project",
                          "right_field": "bio", "right_quote": "invented project",
                          "reason": "same"}]
        raw = json.dumps(obj)
        self.assertTrue(allowed(raw))
        with self.assertRaisesRegex(ValueError, "not present"):
            validate_response(raw, {"bio": "real project"}, {"bio": "real project"})

    def test_schema_failure_has_actionable_diagnostic(self):
        with self.assertRaisesRegex(ValueError, "missing=.*contradictions"):
            validate_response('{"verdict":"insufficient_evidence","matches":[]}', {}, {})

    def test_raw_output_only_exposed_to_explicit_diagnostics(self):
        error = QwenResponseError("bad schema", '{"private":"value"}')
        self.assertEqual(str(error), "bad schema")
        self.assertEqual(error.raw_response, '{"private":"value"}')

    def test_cache_and_generator_share_one_prompt_version(self):
        self.assertEqual(PROMPT_VERSION, CACHE_PROMPT_VERSION)
        self.assertGreater(PROMPT_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
