from __future__ import annotations

import math
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any
import csv

import database

try:
    from sentence_transformers import SentenceTransformer, util
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    SentenceTransformer = None
    util = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class NLPSearchEngine:
    TERM_ALIASES = {
        "python": {"django", "flask", "fastapi", "backend"},
        "backend": {"python", "django", "flask", "fastapi", "api"},
        "devops": {"docker", "kubernetes", "ci", "cd", "linux"},
        "designer": {"figma", "ui", "ux", "behance", "design"},
        "figma": {"designer", "ui", "ux", "design"},
        "osint": {"sherlock", "security", "analyst", "telegram"},
        "analyst": {"osint", "security", "research"},
        "разработчик": {"developer", "backend", "frontend", "python"},
        "дизайнер": {"designer", "figma", "ui", "ux"},
        "аналитик": {"analyst", "osint", "security"},
    }

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        self.model_name = model_name
        self._model = None
        self._rows: list[dict[str, Any]] = []
        self._embeddings = None
        self._doc_vectors: list[dict[str, float]] = []
        self._doc_norms: list[float] = []
        self._idf: dict[str, float] = {}
        self._lock = threading.Lock()
        self._dirty = True
        self._backend = "semantic"

    def invalidate(self) -> None:
        with self._lock:
            self._dirty = True

    def _ensure_model(self) -> None:
        if IMPORT_ERROR is not None:
            self._backend = "lexical"
            return
        if self._model is None:
            try:
                self._model = SentenceTransformer(self.model_name, local_files_only=True)
                self._backend = "semantic"
            except Exception:
                self._backend = "lexical"

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[\w+#.-]+", (text or "").lower(), flags=re.UNICODE)

    @staticmethod
    def _candidate_text(row: dict[str, Any]) -> str:
        return " ".join(
            str(row.get(field) or "")
            for field in ("bio", "group_name", "username", "site_list", "first_name")
        ).lower()

    @classmethod
    def _expanded_query_terms(cls, query: str) -> list[str]:
        terms = set(cls._tokenize(query))
        for term in list(terms):
            terms.update(cls.TERM_ALIASES.get(term, set()))
        return sorted(terms)

    @staticmethod
    def _normalize_score(score: float) -> float:
        return max(0.0, min(float(score), 1.0))

    @staticmethod
    def _osint_boost(row: dict[str, Any]) -> float:
        osint_score = float(row.get("osint_score") or 0) / 100.0
        site_bonus = min(float(row.get("site_count") or 0), 5.0) / 5.0
        professional_sites = sum(
            int(row.get(field) or 0)
            for field in ("has_github", "has_linkedin", "has_behance")
        )
        professional_bonus = min(professional_sites, 3) / 3.0
        return max(0.0, min(osint_score * 0.70 + site_bonus * 0.20 + professional_bonus * 0.10, 1.0))

    def _enrich_result(self, query: str, row: dict[str, Any]) -> dict[str, Any]:
        query_terms = self._expanded_query_terms(query)
        text = self._candidate_text(row)
        matched_terms = [term for term in query_terms if term and term in text]
        match_bonus = min(len(matched_terms), 6) / 6.0
        semantic_score = self._normalize_score(float(row.get("score") or 0.0))
        osint_boost = self._osint_boost(row)

        row["query_terms"] = ", ".join(query_terms)
        row["matched_terms"] = ", ".join(matched_terms)
        row["match_count"] = len(matched_terms)
        row["osint_boost"] = round(osint_boost, 4)
        row["hybrid_score"] = round(
            semantic_score * 0.70 + osint_boost * 0.20 + match_bonus * 0.10,
            4,
        )
        return row

    def _build_lexical_index(self, rows: list[dict[str, Any]]) -> None:
        doc_tokens = [Counter(self._tokenize(row["bio"])) for row in rows]
        doc_freq: Counter[str] = Counter()
        for tokens in doc_tokens:
            for token in tokens:
                doc_freq[token] += 1

        total_docs = max(len(doc_tokens), 1)
        self._idf = {
            token: math.log((1 + total_docs) / (1 + count)) + 1.0
            for token, count in doc_freq.items()
        }
        self._doc_vectors = []
        self._doc_norms = []

        for token_counts in doc_tokens:
            vector = {
                token: count * self._idf.get(token, 1.0)
                for token, count in token_counts.items()
            }
            norm = math.sqrt(sum(value * value for value in vector.values()))
            self._doc_vectors.append(vector)
            self._doc_norms.append(norm)

    def _rebuild_index(self) -> None:
        self._ensure_model()
        rows = database.get_search_dataset()
        texts = [row["bio"] for row in rows]

        if not texts:
            self._rows = []
            self._embeddings = None
            self._doc_vectors = []
            self._doc_norms = []
            self._idf = {}
            self._dirty = False
            return

        self._rows = rows
        if self._backend == "semantic" and self._model is not None:
            self._embeddings = self._model.encode(texts, convert_to_tensor=True)
            self._doc_vectors = []
            self._doc_norms = []
            self._idf = {}
        else:
            self._embeddings = None
            self._build_lexical_index(rows)
        self._dirty = False

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        with self._lock:
            if self._dirty:
                self._rebuild_index()

            if not self._rows:
                return []

            if self._backend == "semantic" and self._embeddings is not None and self._model is not None:
                query_embedding = self._model.encode(query, convert_to_tensor=True)
                hits = util.semantic_search(
                    query_embedding,
                    self._embeddings,
                    top_k=min(top_k, len(self._rows)),
                )[0]

                results: list[dict[str, Any]] = []
                for hit in hits:
                    row = dict(self._rows[hit["corpus_id"]])
                    row["score"] = float(hit["score"])
                    results.append(self._enrich_result(query, row))
                return results

            query_counts = Counter(self._tokenize(query))
            query_vector = {
                token: count * self._idf.get(token, 1.0)
                for token, count in query_counts.items()
            }
            query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
            if query_norm == 0:
                return []

            scored_rows: list[dict[str, Any]] = []
            for index, row in enumerate(self._rows):
                doc_vector = self._doc_vectors[index]
                doc_norm = self._doc_norms[index]
                if doc_norm == 0:
                    continue
                numerator = sum(
                    query_vector[token] * doc_vector.get(token, 0.0)
                    for token in query_vector
                )
                score = numerator / (query_norm * doc_norm)
                if score <= 0:
                    continue
                item = dict(row)
                item["score"] = float(score)
                scored_rows.append(self._enrich_result(query, item))

            scored_rows.sort(key=lambda row: row["score"], reverse=True)
            return scored_rows[:top_k]

    def search_hybrid(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        candidate_count = max(top_k * 5, 50)
        candidates = self.search(query, top_k=candidate_count)
        candidates.sort(
            key=lambda row: (
                float(row.get("hybrid_score") or 0.0),
                float(row.get("score") or 0.0),
                int(row.get("osint_score") or 0),
            ),
            reverse=True,
        )
        return candidates[:top_k]

    def compare_search_modes(self, query: str, top_k: int = 10) -> dict[str, Any]:
        baseline = self.search(query, top_k=top_k)
        hybrid = self.search_hybrid(query, top_k=top_k)
        baseline_ids = {row.get("user_id") for row in baseline}
        hybrid_ids = {row.get("user_id") for row in hybrid}
        return {
            "query": query,
            "backend": self._backend,
            "baseline": baseline,
            "hybrid": hybrid,
            "overlap_count": len(baseline_ids & hybrid_ids),
            "changed_count": len(hybrid_ids - baseline_ids),
        }

    def export_results_csv(self, rows: list[dict[str, Any]], path: Path) -> Path:
        fieldnames = [
            "user_id",
            "first_name",
            "username",
            "score",
            "hybrid_score",
            "osint_score",
            "exposure_level",
            "matched_terms",
            "group_name",
            "site_count",
            "site_list",
            "bio",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(
                [{field: row.get(field, "") for field in fieldnames} for row in rows]
            )
        return path
