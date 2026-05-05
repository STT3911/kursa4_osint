from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

import database


SNOOP_SOURCE_DIR = Path("tools") / "snoop"

RESOURCE_COLUMN = "\u0440\u0435\u0441\u0443\u0440\u0441"
PROFILE_URL_COLUMN = "\u0441\u0441\u044b\u043b\u043a\u0430_\u043d\u0430_\u043f\u0440\u043e\u0444\u0438\u043b\u044c"
STATUS_COLUMN = "\u0441\u0442\u0430\u0442\u0443\u0441"
FOUND_STATUS = "\u043d\u0430\u0439\u0434\u0435\u043d"


def find_snoop_command() -> tuple[list[str], Path] | None:
    env_dir = os.getenv("SNOOP_DIR", "").strip()
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir) / "snoop.py")
    candidates.append(SNOOP_SOURCE_DIR / "snoop.py")

    for candidate in candidates:
        if candidate.exists():
            return [sys.executable, str(candidate.resolve())], candidate.resolve().parent

    for binary_name in ("snoop_cli", "snoop_cli.exe"):
        binary = shutil.which(binary_name)
        if binary:
            return [binary], Path(binary).resolve().parent

    return None


def is_snoop_available() -> bool:
    return find_snoop_command() is not None


def _normal_key(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _get_first(row: dict, keys: tuple[str, ...]) -> str:
    normalized = {_normal_key(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(key)
        if value:
            return str(value).strip()
    return ""


def _is_found_status(value: str) -> bool:
    status = (value or "").strip().lower()
    if not status:
        return True
    negative_markers = ("not found", "false", "no", "missing", "\u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d")
    if any(marker in status for marker in negative_markers):
        return False
    return any(marker in status for marker in (FOUND_STATUS, "found", "true", "yes", "claimed"))


def parse_snoop_csv(csv_path: Path, username: str) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig", errors="replace") as file_obj:
        sample = file_obj.read(4096)
        file_obj.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(file_obj, delimiter=delimiter)
        for row in reader:
            site_name = _get_first(row, (RESOURCE_COLUMN, "resource", "site", "name"))
            profile_url = _get_first(
                row,
                (
                    PROFILE_URL_COLUMN,
                    "url_username",
                    "url_user",
                    "profile_url",
                    "url",
                ),
            )
            status = _get_first(row, (STATUS_COLUMN, "status", "exists"))
            if not site_name or not profile_url or not profile_url.startswith(("http://", "https://")):
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


def _candidate_csv_paths(workdir: Path, username: str) -> list[Path]:
    csv_dir = workdir / "results" / "nicknames" / "csv"
    safe_names = {
        username,
        username.replace(" ", "_"),
        username.replace("@", ""),
    }
    paths = [csv_dir / f"{name}.csv" for name in safe_names if name]
    if csv_dir.exists():
        paths.extend(sorted(csv_dir.glob("*.csv"), key=lambda path: path.stat().st_mtime, reverse=True))
    return paths


def run_snoop(username: str, timeout: int = 90) -> list[dict[str, str]]:
    resolved = find_snoop_command()
    if resolved is None:
        raise RuntimeError(
            "Snoop is not installed. Clone https://github.com/snooppr/snoop to tools/snoop "
            "or set SNOOP_DIR."
        )

    command, workdir = resolved
    username = (username or "").strip().lstrip("@")
    if not username:
        return []

    before = {path.resolve() for path in _candidate_csv_paths(workdir, username) if path.exists()}
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    process = subprocess.run(
        command + ["--no-func", "--found-print", "--time-out", "6", username],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(workdir),
        env=env,
        timeout=timeout,
        check=False,
    )

    csv_candidates = [
        path
        for path in _candidate_csv_paths(workdir, username)
        if path.exists() and path.resolve() not in before
    ]
    if not csv_candidates:
        csv_candidates = [path for path in _candidate_csv_paths(workdir, username) if path.exists()]

    accounts: list[dict[str, str]] = []
    for csv_path in csv_candidates[:3]:
        accounts.extend(parse_snoop_csv(csv_path, username))
        if accounts:
            break

    if process.returncode not in (0, 1):
        stderr = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(stderr or f"Snoop exited with code {process.returncode}")

    return accounts


def process_snoop_check(user_id: int, username: str, timeout: int = 90) -> dict:
    username = (username or "").strip().lstrip("@")
    if not username:
        database.mark_enrichment_skipped(user_id, username, "snoop")
        return {"status": "skipped", "found_count": 0, "message": "Username is empty"}

    if not is_snoop_available():
        database.mark_enrichment_skipped(user_id, username, "snoop")
        return {
            "status": "skipped",
            "found_count": 0,
            "message": "Snoop is not installed; skipped.",
        }

    try:
        accounts = run_snoop(username=username, timeout=timeout)
        found_count = database.save_social_accounts(user_id, username, accounts, source="snoop")
        database.mark_enrichment_done(user_id, username, "snoop", found_count)
        return {
            "status": "done",
            "found_count": found_count,
            "message": f"Snoop found {found_count} accounts for @{username}",
        }
    except Exception as exc:
        database.mark_enrichment_error(user_id, username, "snoop", str(exc))
        return {
            "status": "error",
            "found_count": 0,
            "message": str(exc),
        }
