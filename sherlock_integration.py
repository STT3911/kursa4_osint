from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

import database

SHERLOCK_OUTPUT_DIR = database.RUNTIME_DIR / "sherlock_output"

_USERNAME_RE = re.compile(r"^[\w\-\.]{1,64}$")

def _sanitize_username(username: str) -> str:
    username = (username or "").strip().lstrip("@")
    if not _USERNAME_RE.match(username):
        raise ValueError(f"Invalid username format: {username!r}")
    return username

def find_sherlock_command() -> list[str] | None:
    binary = shutil.which("sherlock")
    if binary:
        return [binary]

    try:
        import sherlock_project
    except ImportError:
        return None
    return [sys.executable, "-m", "sherlock_project"]

def _sherlock_supports_local() -> bool:
    command = find_sherlock_command()
    if command is None:
        return False
    try:
        result = subprocess.run(
            command + ["--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return "--local" in (result.stdout + result.stderr)
    except Exception:
        return False

def is_sherlock_available() -> bool:
    return find_sherlock_command() is not None

_MAX_CSV_BYTES = 8 * 1024 * 1024
_MAX_CSV_ROWS = 5_000

def _parse_csv_output(csv_path: Path, username: str) -> list[dict[str, str]]:
    if csv_path.stat().st_size > _MAX_CSV_BYTES:
        return []
    accounts: list[dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8", errors="replace") as file_obj:
        reader = csv.DictReader(file_obj)
        for _row_idx, row in enumerate(reader):
            if _row_idx >= _MAX_CSV_ROWS:
                break
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

def run_sherlock(username: str, timeout: int = 60) -> list[dict[str, str]]:
    command = find_sherlock_command()
    if command is None:
        raise RuntimeError(
            "Sherlock CLI is not installed. Install 'sherlock-project' before running enrichment."
        )

    username = _sanitize_username(username)

    SHERLOCK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_output_path = SHERLOCK_OUTPUT_DIR / f"{username}.csv"

    base_flags = [
        "--csv",
        "--folderoutput",
        str(SHERLOCK_OUTPUT_DIR),
        "--print-found",
        "--no-color",
        "--timeout",
        "8",
    ]
    if _sherlock_supports_local():
        base_flags = ["--local"] + base_flags

    try:
        if temp_output_path.exists():
            temp_output_path.unlink()

        process = subprocess.run(
            command + base_flags + [username],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=".",
            timeout=timeout,
            check=False,
        )

        if process.returncode == 2:
            flags_no_local = [f for f in base_flags if f != "--local"]
            if temp_output_path.exists():
                temp_output_path.unlink()
            process = subprocess.run(
                command + flags_no_local + [username],
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

def process_username_check(user_id: int, username: str, timeout: int = 60) -> dict:
    username = (username or "").strip().lstrip("@")
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
    except subprocess.TimeoutExpired:
        err = "Sherlock timed out"
        database.mark_username_error(user_id, username, err)
        return {"status": "error", "found_count": 0, "message": err}
    except Exception as exc:
        err = f"Sherlock check failed ({type(exc).__name__})"
        database.mark_username_error(user_id, username, err)
        return {"status": "error", "found_count": 0, "message": err}
