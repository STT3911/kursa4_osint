from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import database
from identity_matcher import (
    FEATURE_NAMES,
    IDENTITY_MODEL_PATH,
    IDENTITY_REPORT_PATH,
    MODELS_DIR,
    IdentityMatcher,
    build_identity_features,
)

try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, roc_auc_score
    from sklearn.model_selection import train_test_split
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "Missing ML dependencies. Install requirements.txt before training: "
        f"{exc}"
    ) from exc


DEFAULT_LABELS_PATH = Path("identity_pairs.csv")

POSITIVE_VALUES = {"1", "true", "yes", "same", "same_person", "match", "тот", "да"}
NEGATIVE_VALUES = {"0", "false", "no", "different", "not_same", "mismatch", "чужой", "нет"}


def _label_to_int(value: str) -> int | None:
    normalized = (value or "").strip().lower()
    if normalized in POSITIVE_VALUES:
        return 1
    if normalized in NEGATIVE_VALUES:
        return 0
    return None


def _row_profile(row: dict[str, str]) -> dict[str, Any]:
    return {
        "user_id": row.get("user_id", ""),
        "first_name": row.get("telegram_name") or row.get("first_name", ""),
        "username": row.get("telegram_username") or row.get("username", ""),
        "bio": row.get("telegram_bio") or row.get("bio", ""),
    }


def _row_account(row: dict[str, str]) -> dict[str, Any]:
    return {
        "site_name": row.get("site_name", ""),
        "profile_url": row.get("profile_url", ""),
        "username": row.get("account_username") or row.get("external_username") or row.get("username", ""),
        "source": row.get("source", ""),
        "display_name": row.get("account_name") or row.get("display_name", ""),
        "bio": row.get("account_bio") or row.get("external_bio", ""),
        "description": row.get("description", ""),
    }


def load_labeled_pairs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(
            f"Training labels file not found: {path}. "
            "Run --export-candidates first, fill the label column, then train."
        )

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj, delimiter=";")
        for raw in reader:
            label = _label_to_int(raw.get("label", ""))
            if label is None:
                continue
            profile = _row_profile(raw)
            account = _row_account(raw)
            if not profile["username"] or not account["profile_url"]:
                continue
            features = build_identity_features(profile, account)
            rows.append(
                {
                    "profile": profile,
                    "account": account,
                    "features": features,
                    "label": label,
                }
            )
    return rows


def export_candidates(path: Path) -> Path:
    database.init_db()
    matcher = IdentityMatcher()
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.user_id,
                p.first_name AS telegram_name,
                p.username AS telegram_username,
                COALESCE(p.bio, '') AS telegram_bio,
                s.site_name,
                s.profile_url,
                s.username AS account_username,
                s.source
            FROM profiles p
            JOIN social_accounts s ON s.user_id = p.user_id
            ORDER BY p.user_id, s.site_name, s.source
            """
        ).fetchall()

    fieldnames = [
        "label",
        "rule_score",
        "rule_verdict",
        "user_id",
        "telegram_name",
        "telegram_username",
        "telegram_bio",
        "site_name",
        "profile_url",
        "account_username",
        "source",
        "account_name",
        "account_bio",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in rows:
            raw = dict(row)
            profile = _row_profile(raw)
            account = _row_account(raw)
            match = matcher.match(profile, account)
            writer.writerow(
                {
                    **raw,
                    "label": "",
                    "rule_score": match["same_person_score"],
                    "rule_verdict": match["identity_verdict"],
                    "account_name": "",
                    "account_bio": "",
                    "notes": "",
                }
            )
    return path


def _build_report(
    rows: list[dict[str, Any]],
    y_test: list[int],
    y_pred: list[int],
    y_prob: list[float],
    classifier_name: str,
    random_state: int,
) -> dict[str, Any]:
    labels = [0, 1]
    try:
        roc_auc = roc_auc_score(y_test, y_prob)
    except ValueError:
        roc_auc = 0.0
    return {
        "task": "identity linkage / same-person account matching",
        "classifier": classifier_name,
        "feature_names": FEATURE_NAMES,
        "rows_total": len(rows),
        "class_distribution": dict(Counter(row["label"] for row in rows)),
        "random_state": random_state,
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "roc_auc": round(float(roc_auc), 4),
        "classification_report": classification_report(
            y_test,
            y_pred,
            labels=labels,
            target_names=["different_person", "same_person"],
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": {
            "labels": ["different_person", "same_person"],
            "matrix": confusion_matrix(y_test, y_pred, labels=labels).tolist(),
        },
        "examples": [
            {
                "label": row["label"],
                "telegram_username": row["profile"].get("username"),
                "site_name": row["account"].get("site_name"),
                "profile_url": row["account"].get("profile_url"),
                "features": row["features"],
            }
            for row in rows[:20]
        ],
    }


def train(args: argparse.Namespace) -> dict[str, Any]:
    rows = load_labeled_pairs(args.labels)
    distribution = Counter(row["label"] for row in rows)
    if len(rows) < args.min_rows:
        raise SystemExit(f"Not enough labeled pairs: {len(rows)}. Need at least {args.min_rows}.")
    if distribution.get(0, 0) < 2 or distribution.get(1, 0) < 2:
        raise SystemExit("Need at least two positive and two negative labeled pairs.")

    x = [[row["features"].get(name, 0.0) for name in FEATURE_NAMES] for row in rows]
    y = [row["label"] for row in rows]

    stratify = y if min(distribution.values()) >= 2 else None
    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=args.test_size,
        random_state=args.random_state,
        stratify=stratify,
    )

    if args.classifier == "random_forest":
        model = RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=args.random_state,
        )
        classifier_name = "RandomForestClassifier"
    else:
        model = LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=args.random_state,
        )
        classifier_name = "LogisticRegression"

    model.fit(x_train, y_train)
    y_pred = list(model.predict(x_test))
    if hasattr(model, "predict_proba"):
        classes = list(getattr(model, "classes_", []))
        probabilities = model.predict_proba(x_test)
        positive_index = classes.index(1)
        y_prob = [float(row[positive_index]) for row in probabilities]
    else:
        y_prob = [float(value) for value in y_pred]

    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "feature_names": FEATURE_NAMES,
            "classifier": classifier_name,
        },
        IDENTITY_MODEL_PATH,
    )
    report = _build_report(
        rows=rows,
        y_test=list(y_test),
        y_pred=y_pred,
        y_prob=y_prob,
        classifier_name=classifier_name,
        random_state=args.random_state,
    )
    IDENTITY_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train same-person identity matcher.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--export-candidates", type=Path)
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--min-rows", type=int, default=20)
    parser.add_argument(
        "--classifier",
        choices=("logistic_regression", "random_forest"),
        default="logistic_regression",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.export_candidates:
        path = export_candidates(args.export_candidates)
        print(f"Identity matching candidates exported: {path}")
        print("Fill the label column with 1 for same person and 0 for different person, then train.")
        return 0

    report = train(args)
    print("Identity matcher training completed.")
    print(f"Model: {IDENTITY_MODEL_PATH}")
    print(f"Report: {IDENTITY_REPORT_PATH}")
    print(f"Accuracy: {report['accuracy']:.4f}")
    print(f"ROC-AUC: {report['roc_auc']:.4f}")
    print("Class distribution:")
    for label, count in sorted(report["class_distribution"].items()):
        print(f"  {label}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
