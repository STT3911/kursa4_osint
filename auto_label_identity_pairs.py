from __future__ import annotations

import argparse
import csv
import shutil
from collections import Counter
from pathlib import Path

from identity_matcher import _extract_username_from_url, compact_identifier


POSITIVE_SITES = {
    "telegram",
    "github",
    "gitlab",
    "linkedin",
    "behance",
    "stackoverflow",
    "dev_to",
    "huggingface",
    "artstation",
    "habr",
    "kaggle",
    "lichess",
}

SEARCH_URL_MARKERS = (
    "search?",
    "/search/",
    "searchpage",
    "q=",
    "query=",
    "keywords=",
)


def _clean_site(value: str) -> str:
    return (value or "").strip().lower()


def _is_search_url(url: str) -> bool:
    url_lower = (url or "").lower()
    return any(marker in url_lower for marker in SEARCH_URL_MARKERS)


def _url_username(row: dict[str, str]) -> str:
    return compact_identifier(_extract_username_from_url(row.get("profile_url", "")))


def _telegram_username(row: dict[str, str]) -> str:
    return compact_identifier(row.get("telegram_username", ""))


def auto_label_row(row: dict[str, str]) -> tuple[str, str]:
    current_label = (row.get("label") or "").strip()
    if current_label:
        return current_label, row.get("notes", "")

    tg_username = _telegram_username(row)
    url_username = _url_username(row)
    account_username = compact_identifier(row.get("account_username", ""))
    site = _clean_site(row.get("site_name", ""))
    score = float(row.get("rule_score") or 0.0)
    notes = (row.get("notes") or "").strip()

    if not tg_username:
        return "", notes

    if url_username and url_username != tg_username and not _is_search_url(row.get("profile_url", "")):
        return "0", _append_note(notes, "auto_label: url username differs from telegram username")

    if (
        site in POSITIVE_SITES
        and account_username == tg_username
        and (url_username == tg_username or site == "stackoverflow")
        and score >= 0.78
    ):
        return "1", _append_note(notes, "auto_label: high-confidence exact username on reliable site")

    if site == "telegram" and account_username == tg_username and score >= 0.70:
        return "1", _append_note(notes, "auto_label: exact Telegram username")

    return "", notes


def _append_note(notes: str, addition: str) -> str:
    if not notes:
        return addition
    if addition in notes:
        return notes
    return f"{notes}; {addition}"


def _synthetic_negative(row: dict[str, str], account_row: dict[str, str]) -> dict[str, str]:
    item = dict(row)
    item["label"] = "0"
    item["site_name"] = account_row.get("site_name", "")
    item["profile_url"] = account_row.get("profile_url", "")
    item["account_username"] = account_row.get("account_username", "")
    item["source"] = account_row.get("source", "")
    item["rule_score"] = ""
    item["rule_verdict"] = "synthetic_different_person"
    item["account_name"] = ""
    item["account_bio"] = ""
    item["notes"] = _append_note(
        item.get("notes", ""),
        f"synthetic_negative: account copied from user_id={account_row.get('user_id', '')}",
    )
    return item


def add_synthetic_negatives(rows: list[dict[str, str]], target_count: int) -> list[dict[str, str]]:
    if target_count <= 0:
        return []

    positives = [row for row in rows if (row.get("label") or "").strip() == "1"]
    if len(positives) < 2:
        return []

    synthetic: list[dict[str, str]] = []
    for index, row in enumerate(positives):
        if len(synthetic) >= target_count:
            break
        for offset in range(1, min(len(positives), 20)):
            candidate = positives[(index + offset) % len(positives)]
            if candidate.get("user_id") != row.get("user_id"):
                synthetic.append(_synthetic_negative(row, candidate))
                break
    return synthetic


def auto_label_file(path: Path, output_path: Path | None, synthetic_negatives: int) -> dict:
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    target = output_path or path
    backup_path = path.with_suffix(path.suffix + ".bak")
    if output_path is None:
        shutil.copy2(path, backup_path)

    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj, delimiter=";")
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    changed = 0
    for row in rows:
        old_label = (row.get("label") or "").strip()
        new_label, notes = auto_label_row(row)
        if not old_label and new_label:
            changed += 1
            row["label"] = new_label
            row["notes"] = notes

    synthetic = add_synthetic_negatives(rows, synthetic_negatives)
    rows.extend(synthetic)

    with target.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    labels = Counter((row.get("label") or "").strip() for row in rows)
    return {
        "path": str(target),
        "backup": str(backup_path) if output_path is None else "",
        "rows": len(rows),
        "auto_labeled_existing_rows": changed,
        "synthetic_negatives_added": len(synthetic),
        "labels": dict(labels),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Conservative weak labeling for identity matching pairs.")
    parser.add_argument("--input", type=Path, default=Path("identity_pairs.csv"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--synthetic-negatives", type=int, default=80)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = auto_label_file(args.input, args.output, args.synthetic_negatives)
    print("Auto-label completed.")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
