from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import joblib
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    joblib = None
    JOBLIB_ERROR = exc
else:
    JOBLIB_ERROR = None

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
CLASSIFIER_PATH = MODELS_DIR / "profile_classifier.joblib"
REPORT_PATH = MODELS_DIR / "profile_classifier_report.json"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

PROFILE_KEYWORDS = {
    "backend": {
        "backend",
        "api",
        "django",
        "flask",
        "fastapi",
        "laravel",
        "php",
        "python",
        "golang",
        "java",
        "node",
        "postgres",
        "sql",
        "разработчик",
        "бэкенд",
        "бекенд",
    },
    "frontend": {
        "frontend",
        "front-end",
        "react",
        "vue",
        "angular",
        "typescript",
        "javascript",
        "html",
        "css",
        "next.js",
        "фронтенд",
    },
    "designer": {
        "designer",
        "design",
        "figma",
        "ui",
        "ux",
        "behance",
        "photoshop",
        "illustrator",
        "дизайнер",
        "дизайн",
    },
    "devops": {
        "devops",
        "docker",
        "kubernetes",
        "linux",
        "ci",
        "cd",
        "ansible",
        "terraform",
        "sre",
        "aws",
        "cloud",
        "девопс",
    },
    "analyst_security": {
        "osint",
        "security",
        "cybersecurity",
        "analyst",
        "research",
        "sherlock",
        "forensics",
        "pentest",
        "secops",
        "аналитик",
        "безопасность",
        "кибербезопасность",
    },
}


def normalize_username(value: str) -> str:
    value = (value or "").strip()
    value = value.removeprefix("@")
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break
    return value.strip("/ ")


def profile_text(row: dict[str, Any]) -> str:
    fields = (
        "first_name",
        "username",
        "bio",
        "group_name",
        "site_list",
        "exposure_level",
    )
    return " ".join(str(row.get(field) or "") for field in fields).strip()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[\w+#.-]+", (text or "").lower(), flags=re.UNICODE)


def infer_profile_class(row: dict[str, Any]) -> tuple[str, float, list[str]]:
    text = profile_text(row).lower()
    tokens = set(tokenize(text))
    scores: Counter[str] = Counter()
    matched: dict[str, list[str]] = {}

    for label, keywords in PROFILE_KEYWORDS.items():
        label_matches = sorted(
            keyword for keyword in keywords if keyword in tokens or keyword in text
        )
        if label_matches:
            scores[label] = len(label_matches)
            matched[label] = label_matches

    if int(row.get("has_github") or 0):
        scores["backend"] += 1
        matched.setdefault("backend", []).append("github")
    if int(row.get("has_linkedin") or 0):
        scores["analyst_security"] += 1
        matched.setdefault("analyst_security", []).append("linkedin")
    if int(row.get("has_behance") or 0):
        scores["designer"] += 2
        matched.setdefault("designer", []).append("behance")

    if not scores:
        return "other", 0.35, []

    label, score = scores.most_common(1)[0]
    confidence = min(0.95, 0.45 + score * 0.12)
    return label, confidence, sorted(set(matched.get(label, [])))


def _format_probability_map(classes: list[str], probabilities: list[float]) -> dict[str, float]:
    return {
        label: round(float(probability), 4)
        for label, probability in sorted(
            zip(classes, probabilities),
            key=lambda item: item[1],
            reverse=True,
        )
    }


class ProfileClassifier:
    def __init__(
        self,
        model_name: str = MODEL_NAME,
        classifier_path: Path = CLASSIFIER_PATH,
    ) -> None:
        self.model_name = model_name
        self.classifier_path = classifier_path
        self._embedding_model = None
        self._classifier = None
        self._classes: list[str] = []
        self._load_classifier()

    @property
    def is_trained(self) -> bool:
        return self._classifier is not None

    def _load_classifier(self) -> None:
        if joblib is None or not self.classifier_path.exists():
            return
        try:
            self.classifier_path.resolve().relative_to(MODELS_DIR.resolve())
        except ValueError:
            return
        artifact = joblib.load(self.classifier_path)
        if isinstance(artifact, dict):
            self._classifier = artifact.get("classifier")
            self._classes = list(artifact.get("classes") or [])
            self.model_name = artifact.get("model_name") or self.model_name
        else:
            self._classifier = artifact
            self._classes = list(getattr(artifact, "classes_", []))

    def _ensure_embedding_model(self) -> bool:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            return False
        if self._embedding_model is not None:
            return True
        try:
            self._embedding_model = SentenceTransformer(self.model_name, local_files_only=True)
            return True
        except Exception:
            return False

    def classify(self, row: dict[str, Any]) -> dict[str, Any]:
        text = profile_text(row)
        if self._classifier is not None and self._ensure_embedding_model():
            vector = self._embedding_model.encode([text], normalize_embeddings=True)
            predicted_label = str(self._classifier.predict(vector)[0])
            if hasattr(self._classifier, "predict_proba"):
                probabilities = self._classifier.predict_proba(vector)[0]
                classes = list(getattr(self._classifier, "classes_", self._classes))
                probability_map = _format_probability_map(classes, probabilities)
                confidence = probability_map.get(predicted_label, 0.0)
            else:
                probability_map = {predicted_label: 1.0}
                confidence = 1.0
            _, _, matched_terms = infer_profile_class(row)
            return {
                "label": predicted_label,
                "confidence": round(float(confidence), 4),
                "source": "trained",
                "probabilities": probability_map,
                "matched_terms": matched_terms,
                "explanation": self.explain(row, predicted_label, confidence, matched_terms, "trained"),
            }

        label, confidence, matched_terms = infer_profile_class(row)
        return {
            "label": label,
            "confidence": round(float(confidence), 4),
            "source": "rules",
            "probabilities": {label: round(float(confidence), 4)},
            "matched_terms": matched_terms,
            "explanation": self.explain(row, label, confidence, matched_terms, "rules"),
        }

    @staticmethod
    def explain(
        row: dict[str, Any],
        label: str,
        confidence: float,
        matched_terms: list[str],
        source: str,
    ) -> str:
        evidence = []
        if matched_terms:
            evidence.append("matched terms: " + ", ".join(matched_terms[:8]))
        if int(row.get("site_count") or 0):
            evidence.append(f"external accounts: {row.get('site_count')}")
        if int(row.get("osint_score") or 0):
            evidence.append(f"OSINT score: {row.get('osint_score')}/100")
        if not evidence:
            evidence.append("not enough strong profile signals")
        return (
            f"{label} ({confidence:.2f}, {source}); "
            + "; ".join(evidence)
        )


def load_training_report() -> dict[str, Any] | None:
    if not REPORT_PATH.exists():
        return None
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
