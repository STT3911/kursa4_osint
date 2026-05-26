from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
import csv

import database

_USERNAME_RE = re.compile(r"^[\w\-\.]{1,64}$")
_MAX_RESULTS = 500

_CLAIMED_STATUSES = {"claimed", "found", "exists", "true"}

_MAIGRET_AVAILABLE: bool | None = None

def _sanitize_username(username: str) -> str:
    username = (username or "").strip().lstrip("@")
    if not _USERNAME_RE.match(username):
        raise ValueError(f"Invalid username format: {username!r}")
    return username

def is_maigret_available() -> bool:
    global _MAIGRET_AVAILABLE
    if _MAIGRET_AVAILABLE is not None:
        return _MAIGRET_AVAILABLE
    try:
        result = subprocess.run(
            [sys.executable, "-m", "maigret", "--version"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        _MAIGRET_AVAILABLE = result.returncode in (0, 1)
    except Exception:
        _MAIGRET_AVAILABLE = False
    return _MAIGRET_AVAILABLE

def _parse_maigret_json(json_path: Path, username: str) -> list[dict[str, str]]:
    if not json_path.exists() or json_path.stat().st_size > 8 * 1024 * 1024:
        return []

    try:
        data: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    accounts: list[dict[str, str]] = []
    roots: list[dict[str, Any]]
    if all(isinstance(value, dict) and ("status" in value or "url" in value or "url_user" in value) for value in data.values()):
        roots = [data]
    else:
        roots = [sites for sites in data.values() if isinstance(sites, dict)]

    for sites in roots:
        for site_name, info in sites.items():
            if not isinstance(info, dict):
                continue
            status = info.get("status") or {}
            if isinstance(status, str):
                status_id = status.lower()
            elif isinstance(status, dict):
                status_id = str(status.get("id") or status.get("status") or "").lower()
            else:
                status_id = ""
            if status_id not in _CLAIMED_STATUSES:
                continue
            url = (
                info.get("url_user")
                or info.get("url")
                or info.get("profile_url")
                or ""
            )
            if not url or not url.startswith(("http://", "https://")):
                continue
            accounts.append({
                "site_name": str(site_name).strip(),
                "profile_url": str(url).strip(),
                "username": username,
            })
            if len(accounts) >= _MAX_RESULTS:
                break

    return accounts

def parse_maigret_json(json_path: Path, username: str) -> list[dict[str, str]]:
    return _parse_maigret_json(json_path, username)

def parse_maigret_csv(csv_path: Path, username: str) -> list[dict[str, str]]:
    if not csv_path.exists() or csv_path.stat().st_size > 8 * 1024 * 1024:
        return []
    accounts: list[dict[str, str]] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig", errors="replace") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            status = str(row.get("exists") or row.get("status") or "").strip().lower()
            if status not in _CLAIMED_STATUSES:
                continue
            site_name = str(row.get("name") or row.get("site") or "").strip()
            url = str(row.get("url_user") or row.get("url") or row.get("profile_url") or "").strip()
            if not site_name or not url.startswith(("http://", "https://")):
                continue
            accounts.append({"site_name": site_name, "profile_url": url, "username": username})
            if len(accounts) >= _MAX_RESULTS:
                break
    return accounts

def run_maigret(username: str, timeout: int = 120, top_sites: int = 500) -> list[dict[str, str]]:
    username = _sanitize_username(username)

    outdir = Path(tempfile.mkdtemp(prefix="maigret_"))
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"

    cmd = [
        sys.executable, "-m", "maigret", username,
        "--no-progressbar", "--no-color",
        "--timeout", "8",
        "--no-recursion",
        "--top-sites", str(top_sites),
        "-J", "simple",
        "--folderoutput", str(outdir),
    ]

    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )

        json_candidates = list(outdir.glob("*.json"))
        accounts: list[dict[str, str]] = []
        for json_file in json_candidates:
            accounts = _parse_maigret_json(json_file, username)
            if accounts:
                break

        if process.returncode not in (0, 1) and not accounts:
            stderr = process.stderr.strip()[:200]
            raise RuntimeError(stderr or f"Maigret exited with code {process.returncode}")

        return accounts

    finally:
        try:
            import shutil
            shutil.rmtree(outdir, ignore_errors=True)
        except OSError:
            pass

def process_maigret_check(user_id: int, username: str, timeout: int = 120) -> dict:
    try:
        username = _sanitize_username(username)
    except ValueError as exc:
        database.mark_enrichment_skipped(user_id, username or "", "maigret")
        return {"status": "skipped", "found_count": 0, "message": str(exc)}

    if not is_maigret_available():
        database.mark_enrichment_skipped(user_id, username, "maigret")
        return {"status": "skipped", "found_count": 0, "message": "Maigret не установлен."}

    try:
        accounts = run_maigret(username=username, timeout=timeout)
        found_count = database.save_social_accounts(user_id, username, accounts, source="maigret")
        database.mark_enrichment_done(user_id, username, "maigret", found_count)
        return {
            "status": "done",
            "found_count": found_count,
            "message": f"Maigret: найдено {found_count} аккаунтов для @{username}",
        }
    except subprocess.TimeoutExpired:
        err = "Maigret timed out"
        database.mark_enrichment_error(user_id, username, "maigret", err)
        return {"status": "timeout", "found_count": 0, "message": err}
    except Exception as exc:
        err = f"Maigret check failed ({type(exc).__name__}): {exc}"
        database.mark_enrichment_error(user_id, username, "maigret", err)
        return {"status": "error", "found_count": 0, "message": err}
