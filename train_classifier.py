from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import database
from ai_classifier import (
    CLASSIFIER_PATH,
    MODEL_NAME,
    MODELS_DIR,
    REPORT_PATH,
    infer_profile_class,
    profile_text,
)

try:
    import joblib
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "Missing ML dependencies. Install requirements.txt before training: "
        f"{exc}"
    ) from exc


def load_rows_from_database() -> list[dict[str, Any]]:
    database.init_db()
    rows = database.get_search_dataset()
    if rows:
        return rows

    if database.BASELINE_DATASET_PATH.exists():
        with database.BASELINE_DATASET_PATH.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.DictReader(file_obj, delimiter=";")
            return [
                {
                    "user_id": row.get("user_id", ""),
                    "first_name": row.get("first_name", ""),
                    "username": row.get("username", ""),
                    "bio": row.get("bio", ""),
                    "photo_path": row.get("photo_path", ""),
                    "group_name": row.get("group_name", ""),
                    "site_list": "",
                    "site_count": 0,
                    "osint_score": 0,
                    "exposure_level": "",
                    "has_github": 0,
                    "has_linkedin": 0,
                    "has_behance": 0,
                }
                for row in reader
                if (row.get("bio") or "").strip()
            ]
    return []


def prepare_training_rows(rows: list[dict[str, Any]], min_confidence: float) -> list[dict[str, Any]]:
    prepared = []
    for row in rows:
        label, confidence, matched_terms = infer_profile_class(row)
        text = profile_text(row)
        if label == "other" or confidence < min_confidence or not text:
            continue
        item = dict(row)
        item["ai_label"] = label
        item["weak_label_confidence"] = confidence
        item["weak_label_terms"] = ", ".join(matched_terms)
        item["training_text"] = text
        prepared.append(item)
    return prepared


def build_report(
    rows: list[dict[str, Any]],
    y_test: list[str],
    y_pred: list[str],
    classes: list[str],
    random_state: int,
) -> dict[str, Any]:
    matrix = confusion_matrix(y_test, y_pred, labels=classes)
    return {
        "model_name": MODEL_NAME,
        "classifier": "LogisticRegression",
        "labeling": "weak labels inferred from profile keywords and OSINT features",
        "rows_total": len(rows),
        "classes": classes,
        "class_distribution": dict(Counter(row["ai_label"] for row in rows)),
        "random_state": random_state,
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "classification_report": classification_report(
            y_test,
            y_pred,
            labels=classes,
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": {
            "labels": classes,
            "matrix": matrix.tolist(),
        },
        "examples": [
            {
                "user_id": row.get("user_id"),
                "username": row.get("username"),
                "label": row.get("ai_label"),
                "terms": row.get("weak_label_terms"),
                "text": row.get("training_text", "")[:240],
            }
            for row in rows[:15]
        ],
    }


def train_classifier(args: argparse.Namespace) -> dict[str, Any]:
    rows = prepare_training_rows(load_rows_from_database(), args.min_confidence)
    class_distribution = Counter(row["ai_label"] for row in rows)
    allowed_classes = {
        label
        for label, count in class_distribution.items()
        if count >= args.min_class_size
    }
    rows = [row for row in rows if row["ai_label"] in allowed_classes]

    if len(allowed_classes) < 2:
        raise SystemExit(
            "Not enough labeled classes for training. Collect more profiles or lower --min-class-size."
        )
    if len(rows) < 10:
        raise SystemExit("Not enough labeled rows for training.")

    labels = [row["ai_label"] for row in rows]
    texts = [row["training_text"] for row in rows]
    train_texts, test_texts, y_train, y_test = train_test_split(
        texts,
        labels,
        test_size=args.test_size,
        random_state=args.random_state,
        stratify=labels,
    )

    embedding_model = SentenceTransformer(MODEL_NAME, local_files_only=args.local_only)
    x_train = embedding_model.encode(
        train_texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    x_test = embedding_model.encode(
        test_texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    classifier = LogisticRegression(
        max_iter=2000,
        class_weight="balanced",
        random_state=args.random_state,
    )
    classifier.fit(x_train, y_train)
    predictions = classifier.predict(x_test)

    MODELS_DIR.mkdir(exist_ok=True)
    artifact = {
        "classifier": classifier,
        "model_name": MODEL_NAME,
        "classes": list(classifier.classes_),
    }
    joblib.dump(artifact, CLASSIFIER_PATH)

    report = build_report(
        rows=rows,
        y_test=list(y_test),
        y_pred=list(predictions),
        classes=list(classifier.classes_),
        random_state=args.random_state,
    )
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train AI profile classifier on sentence-transformer embeddings."
    )
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--min-class-size", type=int, default=3)
    parser.add_argument(
        "--download-model",
        action="store_true",
        help="Allow sentence-transformers to download the embedding model if it is not cached.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.local_only = not args.download_model

    report = train_classifier(args)
    print("AI classifier training completed.")
    print(f"Model: {CLASSIFIER_PATH}")
    print(f"Report: {REPORT_PATH}")
    print(f"Accuracy: {report['accuracy']:.4f}")
    print("Class distribution:")
    for label, count in sorted(report["class_distribution"].items()):
        print(f"  {label}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
