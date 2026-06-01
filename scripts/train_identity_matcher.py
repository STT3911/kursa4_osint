from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    import numpy as np
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
except ImportError as exc:
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

def _find_optimal_threshold(y_test: list[int], y_prob: list[float]) -> float:
    best_f1 = -1.0
    best_thresh = 0.5
    for thresh in [t / 100 for t in range(30, 80, 5)]:
        preds = [1 if p >= thresh else 0 for p in y_prob]
        f1 = f1_score(y_test, preds, pos_label=1, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = thresh
    return best_thresh

def _build_report(
    rows: list[dict[str, Any]],
    y_test: list[int],
    y_pred: list[int],
    y_prob: list[float],
    classifier_name: str,
    random_state: int,
    cv_scores: dict[str, Any] | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    labels = [0, 1]
    try:
        roc_auc = roc_auc_score(y_test, y_prob)
    except ValueError:
        roc_auc = 0.0

    thresh_preds = [1 if p >= threshold else 0 for p in y_prob]

    report: dict[str, Any] = {
        "task": "identity linkage / same-person account matching",
        "classifier": classifier_name,
        "feature_names": FEATURE_NAMES,
        "rows_total": len(rows),
        "class_distribution": dict(Counter(row["label"] for row in rows)),
        "random_state": random_state,
        "decision_threshold": round(threshold, 2),
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "accuracy_at_threshold": round(float(accuracy_score(y_test, thresh_preds)), 4),
        "roc_auc": round(float(roc_auc), 4),
        "precision_same_person": round(float(precision_score(y_test, thresh_preds, pos_label=1, zero_division=0)), 4),
        "recall_same_person": round(float(recall_score(y_test, thresh_preds, pos_label=1, zero_division=0)), 4),
        "f1_same_person": round(float(f1_score(y_test, thresh_preds, pos_label=1, zero_division=0)), 4),
        "classification_report": classification_report(
            y_test,
            thresh_preds,
            labels=labels,
            target_names=["different_person", "same_person"],
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": {
            "labels": ["different_person", "same_person"],
            "matrix": confusion_matrix(y_test, thresh_preds, labels=labels).tolist(),
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
    if cv_scores:
        report["cross_validation"] = cv_scores
    return report

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
        base_model = RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=2,
            max_features="sqrt",
            class_weight="balanced",
            random_state=args.random_state,
        )
        classifier_name = "RandomForestClassifier"
    elif args.classifier == "gradient_boosting":
        base_model = GradientBoostingClassifier(
            n_estimators=200,
            learning_rate=0.08,
            max_depth=4,
            subsample=0.8,
            random_state=args.random_state,
        )
        classifier_name = "GradientBoostingClassifier"
    else:
        base_model = LogisticRegression(
            max_iter=2000,
            C=1.0,
            class_weight="balanced",
            solver="lbfgs",
            random_state=args.random_state,
        )
        classifier_name = "LogisticRegression"

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.random_state)
    cv_roc = cross_val_score(base_model, x, y, cv=cv, scoring="roc_auc")
    cv_f1 = cross_val_score(base_model, x, y, cv=cv, scoring="f1")
    cv_scores = {
        "folds": 5,
        "roc_auc_mean": round(float(np.mean(cv_roc)), 4),
        "roc_auc_std": round(float(np.std(cv_roc)), 4),
        "f1_mean": round(float(np.mean(cv_f1)), 4),
        "f1_std": round(float(np.std(cv_f1)), 4),
    }

    model = CalibratedClassifierCV(base_model, cv=3, method="isotonic")
    model.fit(x_train, y_train)

    y_pred = list(model.predict(x_test))
    classes = list(getattr(model, "classes_", [0, 1]))
    probabilities = model.predict_proba(x_test)
    positive_index = classes.index(1) if 1 in classes else -1
    y_prob = [float(row[positive_index]) for row in probabilities]

    threshold = _find_optimal_threshold(list(y_test), y_prob)
    thresh_preds = [1 if p >= threshold else 0 for p in y_prob]

    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "feature_names": FEATURE_NAMES,
            "classifier": classifier_name,
            "decision_threshold": threshold,
        },
        IDENTITY_MODEL_PATH,
    )
    report = _build_report(
        rows=rows,
        y_test=list(y_test),
        y_pred=thresh_preds,
        y_prob=y_prob,
        classifier_name=classifier_name,
        random_state=args.random_state,
        cv_scores=cv_scores,
        threshold=threshold,
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
        choices=("logistic_regression", "random_forest", "gradient_boosting"),
        default="gradient_boosting",
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
    print(f"Decision threshold: {report['decision_threshold']:.2f}")
    print(f"Accuracy@threshold: {report['accuracy_at_threshold']:.4f}")
    print(f"ROC-AUC: {report['roc_auc']:.4f}")
    print(f"Precision (same_person): {report['precision_same_person']:.4f}")
    print(f"Recall    (same_person): {report['recall_same_person']:.4f}")
    print(f"F1        (same_person): {report['f1_same_person']:.4f}")
    if "cross_validation" in report:
        cv = report["cross_validation"]
        print(
            f"Cross-val ROC-AUC: {cv['roc_auc_mean']:.4f} ± {cv['roc_auc_std']:.4f}  "
            f"F1: {cv['f1_mean']:.4f} ± {cv['f1_std']:.4f}"
        )
    print("Class distribution:")
    for label, count in sorted(report["class_distribution"].items()):
        print(f"  {label}: {count}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
