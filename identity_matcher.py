from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import joblib
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    joblib = None
    JOBLIB_ERROR = exc
else:
    JOBLIB_ERROR = None


BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
IDENTITY_MODEL_PATH = MODELS_DIR / "identity_matcher.joblib"
IDENTITY_REPORT_PATH = MODELS_DIR / "identity_matcher_report.json"

FEATURE_NAMES = [
    "username_similarity",
    "username_exact",
    "username_contains",
    "username_length_quality",
    "name_similarity",
    "bio_url_overlap",
    "professional_site_weight",
    "source_weight",
    "url_depth_quality",
    "collision_risk",
    "site_collision_risk",
    "url_is_search_result",
]

PROFESSIONAL_SITE_WEIGHTS = {
    "github": 1.00,
    "gitlab": 0.95,
    "linkedin": 0.95,
    "behance": 0.90,
    "dribbble": 0.88,
    "stackoverflow": 0.85,
    "habr": 0.80,
    "medium": 0.72,
    "kaggle": 0.85,
    "reddit": 0.48,
    "twitter": 0.55,
    "x": 0.55,
    "instagram": 0.50,
    "facebook": 0.50,
    "vk": 0.45,
    "pinterest": 0.35,
}

# Per-site username collision risk: probability that same username != same person.
# Smaller user bases with unique-username policies have lower collision risk.
SITE_COLLISION_RISK: dict[str, float] = {
    "github": 0.04,
    "gitlab": 0.05,
    "linkedin": 0.08,
    "stackoverflow": 0.07,
    "kaggle": 0.07,
    "habr": 0.10,
    "behance": 0.09,
    "dribbble": 0.09,
    "huggingface": 0.06,
    "dev_to": 0.10,
    "artstation": 0.08,
    "medium": 0.20,
    "telegram": 0.08,
    "twitter": 0.18,
    "x": 0.18,
    "reddit": 0.22,
    "youtube": 0.28,
    "instagram": 0.28,
    "facebook": 0.30,
    "vk": 0.25,
    "tiktok": 0.30,
    "pinterest": 0.35,
    "bandcamp": 0.42,
    "lichess": 0.15,
    "snapchat": 0.30,
    "duolingo": 0.32,
    "rutracker": 0.40,
    "planetaexcel": 0.50,
    "radiokot": 0.52,
    "airliners": 0.60,
    "javaprogrammingforums": 0.55,
}

_SEARCH_URL_MARKERS = (
    "search.php",
    "/search/",
    "search?",
    "searchpage",
    "q=",
    "query=",
    "keywords=",
    "terms=all",
    "find_user",
    "lookup?",
)

SOURCE_WEIGHTS = {
    "sherlock": 0.65,
    "snoop": 0.70,
    "manual": 0.85,
}

GENERIC_USERNAMES = {
    "admin",
    "administrator",
    "user",
    "test",
    "dev",
    "developer",
    "designer",
    "manager",
    "support",
    "info",
    "root",
}


def normalize_identifier(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.removeprefix("@")
    value = re.sub(r"^https?://t\.me/", "", value)
    value = re.sub(r"[^a-z0-9а-яё_ .+-]+", "", value, flags=re.IGNORECASE)
    return value.strip(" /")


def compact_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9а-яё]+", "", normalize_identifier(value), flags=re.IGNORECASE)


def tokenize(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w+#.-]+", (value or "").lower(), flags=re.UNICODE)
        if len(token) >= 3
    }


def _similarity(left: str, right: str) -> float:
    left = compact_identifier(left)
    right = compact_identifier(right)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _extract_username_from_url(profile_url: str) -> str:
    parsed = urlparse(profile_url or "")
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return ""
    ignored = {"user", "users", "u", "profile", "people", "in"}
    for part in reversed(path_parts):
        clean = normalize_identifier(part)
        if clean and clean not in ignored:
            return clean
    return normalize_identifier(path_parts[-1])


def _site_from_url(profile_url: str) -> str:
    host = (urlparse(profile_url or "").netloc or "").lower()
    host = host.removeprefix("www.")
    if not host:
        return ""
    return host.split(".")[0]


def _site_weight(site_name: str, profile_url: str) -> float:
    site = normalize_identifier(site_name) or _site_from_url(profile_url)
    return PROFESSIONAL_SITE_WEIGHTS.get(site, 0.50)


def _site_collision_risk(site_name: str, profile_url: str) -> float:
    site = normalize_identifier(site_name) or _site_from_url(profile_url)
    return SITE_COLLISION_RISK.get(site, 0.35)


def _url_is_search_result(profile_url: str) -> float:
    url_lower = (profile_url or "").lower()
    return 1.0 if any(marker in url_lower for marker in _SEARCH_URL_MARKERS) else 0.0


def _source_weight(source: str) -> float:
    return SOURCE_WEIGHTS.get(normalize_identifier(source), 0.55)


def _length_quality(username: str) -> float:
    username = compact_identifier(username)
    length = len(username)
    if length < 4:
        return 0.15
    if length <= 5:
        return 0.45
    if length <= 14:
        return 1.0
    if length <= 24:
        return 0.75
    return 0.50


def _collision_risk(username: str) -> float:
    normalized = compact_identifier(username)
    if not normalized:
        return 1.0
    if normalized in GENERIC_USERNAMES:
        return 1.0
    if len(normalized) < 5:
        return 0.85
    if normalized.isdigit():
        return 0.90
    digit_share = sum(char.isdigit() for char in normalized) / max(len(normalized), 1)
    if digit_share > 0.5:
        return 0.70
    return 0.20


def _bio_url_overlap(profile: dict[str, Any], account: dict[str, Any]) -> float:
    bio_tokens = tokenize(str(profile.get("bio") or ""))
    if not bio_tokens:
        return 0.0
    external_text = " ".join(
        str(account.get(field) or "")
        for field in ("site_name", "profile_url", "username", "display_name", "bio", "description")
    )
    external_tokens = tokenize(external_text)
    if not external_tokens:
        return 0.0
    overlap = bio_tokens & external_tokens
    return min(len(overlap) / min(len(bio_tokens), 8), 1.0)


def build_identity_features(profile: dict[str, Any], account: dict[str, Any]) -> dict[str, float]:
    telegram_username = normalize_identifier(str(profile.get("username") or ""))
    account_username = normalize_identifier(str(account.get("username") or ""))
    url_username = _extract_username_from_url(str(account.get("profile_url") or ""))
    external_username = account_username or url_username

    username_similarity = max(
        _similarity(telegram_username, account_username),
        _similarity(telegram_username, url_username),
    )
    compact_tg = compact_identifier(telegram_username)
    compact_external = compact_identifier(external_username)
    username_exact = 1.0 if compact_tg and compact_tg == compact_external else 0.0
    username_contains = 0.0
    if compact_tg and compact_external:
        username_contains = 1.0 if compact_tg in compact_external or compact_external in compact_tg else 0.0

    first_name = str(profile.get("first_name") or "")
    display_name = str(account.get("display_name") or account.get("name") or external_username)
    name_similarity = _similarity(first_name, display_name)

    profile_url = str(account.get("profile_url") or "")
    url_depth = len([part for part in urlparse(profile_url).path.split("/") if part])
    url_depth_quality = 1.0 if 1 <= url_depth <= 3 else 0.45

    site_name = str(account.get("site_name") or "")
    source = str(account.get("source") or "")

    return {
        "username_similarity": round(username_similarity, 4),
        "username_exact": username_exact,
        "username_contains": username_contains,
        "username_length_quality": round(_length_quality(telegram_username), 4),
        "name_similarity": round(name_similarity, 4),
        "bio_url_overlap": round(_bio_url_overlap(profile, account), 4),
        "professional_site_weight": round(_site_weight(site_name, profile_url), 4),
        "source_weight": round(_source_weight(source), 4),
        "url_depth_quality": url_depth_quality,
        "collision_risk": round(_collision_risk(telegram_username), 4),
        "site_collision_risk": round(_site_collision_risk(site_name, profile_url), 4),
        "url_is_search_result": _url_is_search_result(profile_url),
    }


def _rule_score(features: dict[str, float]) -> float:
    positive = (
        features["username_similarity"] * 0.32
        + features["username_exact"] * 0.14
        + features["username_contains"] * 0.06
        + features["username_length_quality"] * 0.06
        + features["name_similarity"] * 0.08
        + features["bio_url_overlap"] * 0.10
        + features["professional_site_weight"] * 0.07
        + features["source_weight"] * 0.05
        + features["url_depth_quality"] * 0.02
    )
    penalty = (
        features["collision_risk"] * 0.12
        + features["site_collision_risk"] * 0.10
        + features["url_is_search_result"] * 0.18
    )
    score = positive - penalty
    if features["username_exact"] and features["professional_site_weight"] >= 0.8:
        score += 0.08
    if features["username_similarity"] < 0.55:
        score -= 0.12
    if features["url_is_search_result"]:
        score -= 0.10
    return max(0.0, min(score, 1.0))


def _verdict(score: float) -> str:
    if score >= 0.75:
        return "likely_same_person"
    if score >= 0.55:
        return "possible_same_person"
    return "unlikely_same_person"


def _risk_label(score: float) -> str:
    if score >= 0.75:
        return "low_false_positive_risk"
    if score >= 0.55:
        return "medium_false_positive_risk"
    return "high_false_positive_risk"


def _explain(features: dict[str, float], score: float) -> str:
    reasons: list[str] = []
    if features["username_exact"]:
        reasons.append("username matches exactly")
    elif features["username_similarity"] >= 0.8:
        reasons.append(f"username is similar ({features['username_similarity']:.2f})")
    elif features["username_similarity"] < 0.55:
        reasons.append(f"username similarity is weak ({features['username_similarity']:.2f})")
    if features["bio_url_overlap"] >= 0.25:
        reasons.append(f"profile text overlaps with account URL/site ({features['bio_url_overlap']:.2f})")
    if features["name_similarity"] >= 0.7:
        reasons.append(f"name is similar ({features['name_similarity']:.2f})")
    if features["professional_site_weight"] >= 0.8:
        reasons.append("site is professionally informative")
    if features["collision_risk"] >= 0.7:
        reasons.append("username has high collision risk")
    if not reasons:
        reasons.append("not enough strong identity evidence")
    return f"{_verdict(score)} ({score:.2f}); " + "; ".join(reasons)


class IdentityMatcher:
    def __init__(
        self,
        model_path: Path = IDENTITY_MODEL_PATH,
        report_path: Path = IDENTITY_REPORT_PATH,
        min_roc_auc: float = 0.55,
    ) -> None:
        self.model_path = model_path
        self.report_path = report_path
        self.min_roc_auc = min_roc_auc
        self._model = None
        self._feature_names = FEATURE_NAMES
        self._threshold = 0.5
        self.disabled_reason = ""
        self._load_model()

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def _load_model(self) -> None:
        if joblib is None or not self.model_path.exists():
            return
        try:
            self.model_path.resolve().relative_to(MODELS_DIR.resolve())
        except ValueError:
            self.disabled_reason = "model path escapes models directory — refused to load"
            return
        if self.report_path.exists():
            report = json.loads(self.report_path.read_text(encoding="utf-8"))
            roc_auc = float(report.get("roc_auc") or 0.0)
            if roc_auc and roc_auc < self.min_roc_auc:
                self.disabled_reason = (
                    f"trained model disabled: ROC-AUC {roc_auc:.4f} is below {self.min_roc_auc:.2f}"
                )
                return
        artifact = joblib.load(self.model_path)
        if isinstance(artifact, dict):
            stored_features = list(artifact.get("feature_names") or FEATURE_NAMES)
            if stored_features != FEATURE_NAMES:
                self.disabled_reason = (
                    f"trained model disabled: feature schema mismatch "
                    f"(stored {len(stored_features)} features, current {len(FEATURE_NAMES)}). "
                    "Re-train with train_identity_matcher.py."
                )
                return
            self._model = artifact.get("model")
            self._feature_names = stored_features
            self._threshold = float(artifact.get("decision_threshold") or 0.5)
        else:
            self._model = artifact

    def _predict_score(self, features: dict[str, float]) -> tuple[float, str]:
        if self._model is None:
            return _rule_score(features), "rules"
        vector = [[features.get(name, 0.0) for name in self._feature_names]]
        if hasattr(self._model, "predict_proba"):
            classes = list(getattr(self._model, "classes_", []))
            probabilities = self._model.predict_proba(vector)[0]
            if 1 in classes:
                raw_prob = float(probabilities[classes.index(1)])
            else:
                raw_prob = float(max(probabilities))
            calibrated = raw_prob / (raw_prob + (1 - raw_prob) * (self._threshold / (1 - self._threshold + 1e-9)))
            return min(calibrated, 1.0), "trained"
        prediction = float(self._model.predict(vector)[0])
        return max(0.0, min(prediction, 1.0)), "trained"

    def match(self, profile: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
        features = build_identity_features(profile, account)
        score, source = self._predict_score(features)
        score = max(0.0, min(float(score), 1.0))
        return {
            "same_person_score": round(score, 4),
            "same_person_percent": int(round(score * 100)),
            "identity_verdict": _verdict(score),
            "false_positive_risk": _risk_label(score),
            "identity_source": source,
            "identity_features": features,
            "identity_explanation": _explain(features, score),
        }

    def match_many(self, profile: dict[str, Any], accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched = []
        for account in accounts:
            item = dict(account)
            item.update(self.match(profile, account))
            enriched.append(item)
        return sorted(enriched, key=lambda row: row["same_person_score"], reverse=True)


def load_identity_report() -> dict[str, Any] | None:
    if not IDENTITY_REPORT_PATH.exists():
        return None
    return json.loads(IDENTITY_REPORT_PATH.read_text(encoding="utf-8"))


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))
