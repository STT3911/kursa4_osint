"""Run only SpiderFoot's account finder in its own Python environment."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from config import env_first

ACCOUNT_TYPES = {"ACCOUNT_EXTERNAL_OWNED", "SIMILAR_ACCOUNT_EXTERNAL",
                 "Account on External Site", "Similar Account on External Site"}
_MAX_BYTES = 8 * 1024 * 1024


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Expected an HTTP(S) profile URL")
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not allowed in profile URLs")
    # Preserve case-sensitive paths and query parameters.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path.rstrip("/") or "/", parsed.query, ""))


def _username(value: str) -> str:
    value = (value or "").strip().lstrip("@")
    if not re.fullmatch(r"[\w.-]{1,64}", value):
        raise ValueError("Invalid username")
    return value


def _settings() -> tuple[Path, str]:
    directory = env_first("SPIDERFOOT_DIR")
    executable = env_first("SPIDERFOOT_PYTHON")
    if not directory or not executable:
        raise RuntimeError("Задайте SPIDERFOOT_DIR и SPIDERFOOT_PYTHON в .env")
    script = Path(directory).expanduser().resolve() / "sf.py"
    if not script.is_file():
        raise RuntimeError("В SPIDERFOOT_DIR не найден sf.py")
    if not Path(executable).expanduser().is_file():
        raise RuntimeError("SPIDERFOOT_PYTHON должен указывать на Python отдельного окружения")
    return script, str(Path(executable).expanduser().resolve())


def is_spiderfoot_available() -> bool:
    try:
        _settings()
    except (RuntimeError, OSError):
        return False
    return True


def parse_spiderfoot_json(output: str, username: str) -> list[dict]:
    """CLI replaces event codes with human-readable event labels."""
    if len(output.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("SpiderFoot output exceeds 8 MiB")
    events = json.loads(output)
    if not isinstance(events, list):
        raise ValueError("SpiderFoot must return a JSON event array")
    accounts = {}
    for event in events:
        if not isinstance(event, dict) or event.get("module") != "sfp_accounts":
            continue
        if event.get("type") not in ACCOUNT_TYPES:
            continue
        # Do not attach a different seed/permutation to the requested username.
        if str(event.get("source") or "").casefold() != username.casefold():
            continue
        data = str(event.get("data") or "")
        found = re.search(r"<SFURL>(https?://[^<\s]+)</SFURL>", data)
        if not found:
            # sfp__stor_stdout removes SFURL markup before outputting data.
            found = re.search(r"https?://[^\s<>]+", data)
        if not found:
            continue
        try:
            url = canonical_url(found.group(1) if found.lastindex else found.group())
        except ValueError:
            continue
        site = data.split(" (Category:", 1)[0].split("\n", 1)[0].strip()
        accounts.setdefault(url, {
            "site_name": site[:120] or urlsplit(url).hostname,
            "profile_url": url, "username": "",
            "queried_username": username, "source": "spiderfoot",
            "identity_status": "candidate",
        })
        if len(accounts) >= 500:
            break
    return list(accounts.values())


def run_spiderfoot(username: str, timeout: int = 180) -> list[dict]:
    username = _username(username)
    script, executable = _settings()
    command = [executable, str(script), "-s", f'"{username}"', "-m", "sfp_accounts",
               "-F", "ACCOUNT_EXTERNAL_OWNED,SIMILAR_ACCOUNT_EXTERNAL", "-o", "json"]
    env = os.environ.copy()
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    # Current-run stdout only: no shared report directory or stale result fallback.
    result = subprocess.run(command, cwd=script.parent, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("SpiderFoot завершился с ошибкой: " + result.stderr[-500:])
    # Fail closed on logs mixed into stdout / truncated JSON.
    return parse_spiderfoot_json(result.stdout.strip(), username)


def process_spiderfoot_check(user_id: int, username: str, timeout: int = 180) -> dict:
    import database
    try:
        accounts = run_spiderfoot(username, timeout)
        count = database.save_social_accounts(user_id, username, accounts, source="spiderfoot")
        database.mark_enrichment_done(user_id, username, "spiderfoot", count)
        return {"status": "done", "found_count": count,
                "message": f"SpiderFoot: найдено кандидатов — {count}"}
    except Exception as exc:
        database.mark_enrichment_error(user_id, username, "spiderfoot", str(exc))
        return {"status": "error", "found_count": 0, "message": str(exc)}
