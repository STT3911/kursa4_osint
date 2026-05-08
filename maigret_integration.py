from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import database


MAIGRET_OUTPUT_DIR = database.RUNTIME_DIR / "maigret_output"


def find_maigret_command() -> list[str] | None:
    binary = shutil.which("maigret")
    if binary:
        return [binary]

    scripts_dir = Path(sys.executable).resolve().parent
    for candidate in (scripts_dir / "maigret.exe", scripts_dir / "maigret"):
        if candidate.exists():
            return [str(candidate)]

    try:
        import maigret  # noqa: F401
    except ImportError:
        return None
    return [sys.executable, "-m", "maigret"]


def is_maigret_available() -> bool:
    return find_maigret_command() is not None


def _is_found_status(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    negative_markers = ("not found", "unclaimed", "available", "false", "no")
    if any(marker in text for marker in negative_markers):
        return False
    return any(marker in text for marker in ("claimed", "found", "true", "yes"))


def _safe_report_username(username: str) -> str:
    return (username or "").strip().lstrip("@").replace("/", "_")


def parse_maigret_csv(csv_path: Path, username: str) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8", errors="replace") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            lowered = {str(key).lower(): value for key, value in row.items()}
            site_name = str(lowered.get("name") or lowered.get("site") or "").strip()
            profile_url = str(
                lowered.get("url_user")
                or lowered.get("profile_url")
                or lowered.get("url")
                or ""
            ).strip()
            status = lowered.get("exists") or lowered.get("status")
            if not site_name or not profile_url.startswith(("http://", "https://")):
                continue
            if not _is_found_status(status):
                continue
            accounts.append(
                {
                    "site_name": site_name,
                    "profile_url": profile_url,
                    "username": username,
                }
            )
    return accounts


def parse_maigret_json(json_path: Path, username: str) -> list[dict[str, str]]:
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    accounts: list[dict[str, str]] = []
    if isinstance(payload, dict):
        iterator = payload.items()
    else:
        iterator = []

    for site_name, data in iterator:
        if not isinstance(data, dict):
            continue
        status = data.get("status")
        if isinstance(status, dict):
            status_value = status.get("status") or status.get("name") or status.get("message")
        else:
            status_value = status
        profile_url = str(
            data.get("url_user")
            or data.get("profile_url")
            or data.get("url")
            or ""
        ).strip()
        if not profile_url.startswith(("http://", "https://")):
            continue
        if not _is_found_status(status_value):
            continue
        accounts.append(
            {
                "site_name": str(site_name).strip(),
                "profile_url": profile_url,
                "username": username,
            }
        )
    return accounts


def run_maigret(
    username: str,
    timeout: int = 180,
    site_timeout: int = 10,
    top_sites: int = 500,
) -> list[dict[str, str]]:
    command = find_maigret_command()
    if command is None:
        raise RuntimeError("Maigret is not installed. Install 'maigret' before running enrichment.")

    username = (username or "").strip().lstrip("@")
    if not username:
        return []

    MAIGRET_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_username = _safe_report_username(username)
    csv_path = MAIGRET_OUTPUT_DIR / f"report_{safe_username}.csv"
    json_path = MAIGRET_OUTPUT_DIR / f"report_{safe_username}_simple.json"

    for path in (csv_path, json_path):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    process = subprocess.run(
        command
        + [
            username,
            "--no-autoupdate",
            "--no-recursion",
            "--no-extracting",
            "--csv",
            "--json",
            "simple",
            "--folderoutput",
            str(MAIGRET_OUTPUT_DIR),
            "--top-sites",
            str(top_sites),
            "--timeout",
            str(site_timeout),
            "--no-color",
            "--no-progressbar",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(database.BASE_DIR),
        timeout=timeout,
        check=False,
    )

    accounts: list[dict[str, str]] = []
    if csv_path.exists():
        accounts = parse_maigret_csv(csv_path, username)
    if not accounts and json_path.exists():
        accounts = parse_maigret_json(json_path, username)

    if process.returncode not in (0, 1):
        stderr = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(stderr or f"Maigret exited with code {process.returncode}")

    return accounts


def process_maigret_check(user_id: int, username: str, timeout: int = 180) -> dict:
    username = (username or "").strip().lstrip("@")
    if not username:
        database.mark_enrichment_skipped(user_id, username, "maigret")
        return {"status": "skipped", "found_count": 0, "message": "Username is empty"}

    if not is_maigret_available():
        database.mark_enrichment_skipped(user_id, username, "maigret")
        return {
            "status": "skipped",
            "found_count": 0,
            "message": "Maigret is not installed; skipped.",
        }

    try:
        accounts = run_maigret(username=username, timeout=timeout)
        found_count = database.save_social_accounts(user_id, username, accounts, source="maigret")
        database.mark_enrichment_done(user_id, username, "maigret", found_count)
        return {
            "status": "done",
            "found_count": found_count,
            "message": f"Maigret found {found_count} accounts for @{username}",
        }
    except Exception as exc:
        database.mark_enrichment_error(user_id, username, "maigret", str(exc))
        return {
            "status": "error",
            "found_count": 0,
            "message": str(exc),
        }
