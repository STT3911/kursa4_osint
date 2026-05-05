from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

import database


SHERLOCK_OUTPUT_DIR = database.RUNTIME_DIR / "sherlock_output"


def find_sherlock_command() -> list[str] | None:
    binary = shutil.which("sherlock")
    if binary:
        return [binary]

    try:
        import sherlock_project
    except ImportError:
        return None
    return [sys.executable, "-m", "sherlock_project"]


def is_sherlock_available() -> bool:
    return find_sherlock_command() is not None


def _parse_csv_output(csv_path: Path, username: str) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8", errors="replace") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            lowered = {str(key).lower(): value for key, value in row.items()}
            site_name = (
                lowered.get("site")
                or lowered.get("name")
                or lowered.get("website")
                or lowered.get("social media")
                or lowered.get("social_network")
                or ""
            )
            profile_url = (
                lowered.get("url_user")
                or lowered.get("url")
                or lowered.get("profile_url")
                or lowered.get("user_url")
                or ""
            )
            status = (lowered.get("exists") or lowered.get("status") or "").lower()
            if status and status not in {"true", "found", "claimed", "yes"}:
                continue
            if site_name and profile_url:
                accounts.append(
                    {
                        "site_name": str(site_name).strip(),
                        "profile_url": str(profile_url).strip(),
                        "username": username,
                    }
                )
    return accounts


def _parse_stdout(stdout_text: str, username: str) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    pattern = re.compile(
        r"^(?:\[\+\]\s*)?(?P<site>[^:]+):\s*(?P<url>https?://\S+)$",
        re.IGNORECASE,
    )
    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line or "http" not in line:
            continue
        match = pattern.match(line)
        if not match:
            continue
        accounts.append(
            {
                "site_name": match.group("site").strip(),
                "profile_url": match.group("url").strip(),
                "username": username,
            }
        )
    return accounts


def run_sherlock(username: str, timeout: int = 45) -> list[dict[str, str]]:
    command = find_sherlock_command()
    if command is None:
        raise RuntimeError(
            "Sherlock CLI is not installed. Install 'sherlock-project' before running enrichment."
        )

    SHERLOCK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_output_path = SHERLOCK_OUTPUT_DIR / f"{username}.csv"
    try:
        if temp_output_path.exists():
            temp_output_path.unlink()

        process = subprocess.run(
            command
            + [
                "--local",
                "--csv",
                "--folderoutput",
                str(SHERLOCK_OUTPUT_DIR),
                "--print-found",
                "--no-color",
                username,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=".",
            timeout=timeout,
            check=False,
        )

        accounts: list[dict[str, str]] = []
        if temp_output_path.exists():
            accounts = _parse_csv_output(temp_output_path, username)
        if not accounts:
            accounts = _parse_stdout(process.stdout, username)

        if process.returncode not in (0, 1):
            stderr = process.stderr.strip() or process.stdout.strip()
            raise RuntimeError(stderr or f"Sherlock exited with code {process.returncode}")

        return accounts
    finally:
        try:
            if temp_output_path.exists():
                temp_output_path.unlink()
        except OSError:
            pass


def process_username_check(user_id: int, username: str, timeout: int = 45) -> dict:
    username = (username or "").strip()
    if not username:
        database.mark_username_skipped(user_id, username)
        return {"status": "skipped", "found_count": 0, "message": "Username is empty"}

    try:
        accounts = run_sherlock(username=username, timeout=timeout)
        found_count = database.save_social_accounts(user_id, username, accounts)
        database.mark_username_done(user_id, username, found_count)
        return {
            "status": "done",
            "found_count": found_count,
            "message": f"Sherlock found {found_count} accounts for @{username}",
        }
    except Exception as exc:
        database.mark_username_error(user_id, username, str(exc))
        return {
            "status": "error",
            "found_count": 0,
            "message": str(exc),
        }
