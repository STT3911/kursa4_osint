"""Explicit Qwen review jobs and snapshot-bound persistence in the existing SQLite DB."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

import database
from qwen_identity import PROMPT_VERSION, get_reviewer, insufficient, record

MODEL_DISPLAY_NAME = "Модель сопоставления профилей"
from spiderfoot_integration import canonical_url



class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_public_account(profile_url: str) -> dict:
    """First supported adapter: public GitHub user metadata, not arbitrary URLs."""
    parsed = urlsplit(profile_url)
    login = parsed.path.strip("/")
    if (parsed.scheme != "https" or parsed.netloc.lower() not in {"github.com", "www.github.com"}
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", login)
            or parsed.query or parsed.fragment):
        return {"fetch_status": "unsupported", "profile_url": profile_url}
    endpoint = "https://api.github.com/users/" + quote(login, safe="")
    request = Request(endpoint, headers={"User-Agent": "kursa4-osint",
                                        "Accept": "application/vnd.github+json"})
    # Fixed API origin; never follow a redirect to an arbitrary host.
    with build_opener(_NoRedirect).open(request, timeout=15) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("GitHub response exceeds 1 MiB")
    data = json.loads(raw)
    if not isinstance(data, dict) or not data.get("login") or data.get("type") != "User":
        return {"fetch_status": "not_a_person_profile", "profile_url": profile_url}
    return {"observed_username": str(data["login"]), "display_name": data.get("name") or "",
            "bio": data.get("bio") or "", "links": data.get("blog") or "",
            "profile_url": profile_url, "evidence_url": endpoint, "fetch_status": "ok"}


def _signature(profile: dict) -> str:
    raw = json.dumps(record(profile, telegram=True), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _ensure_table(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS qwen_identity_reviews (
        user_id INTEGER NOT NULL, profile_url TEXT NOT NULL,
        profile_signature TEXT NOT NULL, discovery_signature TEXT NOT NULL,
        model_id TEXT NOT NULL, prompt_version INTEGER NOT NULL,
        result_json TEXT NOT NULL, checked_at TEXT NOT NULL,
        PRIMARY KEY (user_id, profile_url)
    )""")
    conn.commit()


def _discovery_signature(account: dict) -> str:
    return hashlib.sha256(str(account.get("checked_at") or "").encode()).hexdigest()


def load_reviews(user_id: int, profile: dict, accounts: list[dict]) -> dict:
    """Expired, changed-source or changed-profile reviews are not reused."""
    by_url = {}
    for account in accounts:
        try:
            by_url.setdefault(canonical_url(account["profile_url"]), []).append(account)
        except ValueError:
            continue
    model_id = get_reviewer().model_id
    with database.get_connection() as conn:
        _ensure_table(conn)
        rows = conn.execute("SELECT * FROM qwen_identity_reviews WHERE user_id = ?",
                            (user_id,)).fetchall()
    result = {}
    now = datetime.now(timezone.utc)
    for raw in rows:
        row = dict(raw)
        candidates = by_url.get(row["profile_url"], [])
        if (not candidates or row["profile_signature"] != _signature(profile)
                or row["model_id"] != model_id or row["prompt_version"] != PROMPT_VERSION
                or not any(row["discovery_signature"] == _discovery_signature(a)
                           for a in candidates)):
            continue
        if (now - datetime.fromisoformat(row["checked_at"])).total_seconds() > 86400:
            continue
        result[row["profile_url"]] = json.loads(row["result_json"])
    return result


def format_review(result: dict) -> str:
    labels = {"likely_same_person": "Вероятное совпадение",
              "possible_same_person": "Возможное совпадение",
              "unlikely_same_person": "Есть противоречия",
              "insufficient_evidence": "Недостаточно данных"}
    parts = [MODEL_DISPLAY_NAME + ": " + labels.get(result["verdict"], result["verdict"])]
    if result.get("summary"):
        parts.append(result["summary"])
    for key, label in (("matches", "Совпадение"), ("contradictions", "Противоречие")):
        for item in result.get(key, []):
            parts.append(f"{label}: {item['left_quote']} / {item['right_quote']}: {item['reason']}")
    parts.append("Оценка LLM без калибровки; вероятность не рассчитана.")
    return "\n".join(parts)


def process_qwen_review(user_id: int, limit: int = 20) -> dict:
    """Called by a button or CLI, never by routine card rendering."""
    try:
        card = database.get_profile_card(user_id)
        profile = card["profile"]
        unique = {}
        for account in card["social_accounts"]:
            unique.setdefault(canonical_url(account["profile_url"]), account)
        if len(unique) > limit:
            return {"status": "error", "message":
                    f"Найдено {len(unique)} URL. Для полной проверки увеличьте --limit в CLI."}
        cached = load_reviews(user_id, profile, list(unique.values()))
        completed, failures = 0, []
        for url, account in unique.items():
            if url in cached:
                completed += 1
                continue
            try:
                evidence = fetch_public_account(url)
                if evidence["fetch_status"] == "ok":
                    result = get_reviewer().review(profile, evidence)
                else:
                    result = insufficient("Для этой площадки пока нет адаптера открытых данных.")
                result["evidence"] = evidence
                result["checked_at"] = datetime.now(timezone.utc).isoformat()
                with database.get_connection() as conn:
                    _ensure_table(conn)
                    conn.execute("""INSERT OR REPLACE INTO qwen_identity_reviews
                        (user_id, profile_url, profile_signature, discovery_signature,
                         model_id, prompt_version, result_json, checked_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (user_id, url, _signature(profile), _discovery_signature(account),
                         get_reviewer().model_id, PROMPT_VERSION,
                         json.dumps(result, ensure_ascii=False), result["checked_at"]))
                    conn.commit()
                completed += 1
            except Exception as exc:
                # Never turn network/model/JSON failures into an identity verdict.
                failures.append(f"{url}: {type(exc).__name__}: {exc}")
        return {"status": "error" if failures else "done", "found_count": completed,
                "message": f"{MODEL_DISPLAY_NAME}: сохранено разборов — {completed}."
                           + ("\n" + "\n".join(failures) if failures else "")}
    except Exception as exc:
        return {"status": "error", "message": f"{MODEL_DISPLAY_NAME}: {type(exc).__name__}: {exc}"}
