from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Threat keyword taxonomy
# ---------------------------------------------------------------------------

THREAT_KEYWORDS: dict[str, set[str]] = {
    "high_risk": {
        "exploit", "payload", "reverse shell", "c2", "command and control",
        "rat", "rootkit", "keylogger", "metasploit", "meterpreter",
        "sqlmap", "cobalt strike", "mimikatz", "darkweb", "dark web",
        "malware", "ransomware", "ddos", "botnet", "cracker", "cracking",
        "password cracking", "зловред", "взломщик", "хакер",
        "exploit kit", "zero day", "0day", "zero-day", "нулевой день",
    },
    "medium_risk": {
        "pentest", "pentesting", "penetration", "red team", "ctf",
        "hacker", "hacking", "vulnerability", "injection", "xss", "sqli",
        "recon", "reconnaissance", "social engineering", "phishing",
        "vishing", "пентест", "взлом", "уязвимость", "фишинг",
        "брутфорс", "brute force", "bruteforce",
        "osint", "шерлок", "intelligence gathering",
    },
    "analyst": {
        "security analyst", "security researcher", "bug bounty",
        "ethical hacker", "white hat", "defender", "soc analyst",
        "threat intelligence", "forensics", "malware analyst",
        "cyber", "infosec", "аналитик безопасности", "кибербезопасность",
        "исследователь безопасности", "threat hunter",
    },
}

PRIVACY_TOOLS = {
    "tor", "vpn", "tails", "whonix", "protonmail", "tutanota",
    "signal", "pgp", "gpg", "анонимность", "анонимный", "privacy",
    "i2p", "wireguard", "openvpn",
}

EXPOSURE_SIGNALS = {
    "мой телефон", "my phone", "звоните", "позвоните", "call me",
    "email:", "почта:", "живу в", "я из", "адрес:", "address:",
    "вотсап", "whatsapp", "telegram:", "tg:",
}

SUSPICIOUS_BIO_PATTERNS = [
    re.compile(r"\+\d[\d\s\-]{7,}", re.IGNORECASE),    # phone numbers
    re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),  # IP addresses
    re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE),  # emails in bio
    re.compile(r"(?:payme|paypal|qiwi|webmoney)[\s:/]", re.IGNORECASE),      # payment links
]

HIGH_RISK_SITES = {
    "exploit", "nulled", "cracked", "leakbase", "raidforums",
    "hackforums", "darknet", "onion",
}

PROFESSIONAL_SECURITY_SITES = {
    "hackerone", "bugcrowd", "intigriti", "yeswehack",
    "tryhackme", "hackthebox", "ctftime",
}


# Context markers that negate threat meaning of a keyword.
# If found within ±55 chars of the keyword → false positive → skip.
_NEGATION_MARKERS = (
    "защита от", "protection from", "anti-", "против ", "prevent",
    "defend", "block", "stop ", "бороться с", "противодействие",
    "security researcher", "исследователь", "academic", "учебн",
    "курс ", "study", "learn ", "обучени", "конференц",
    "тренинг", "awareness", "осведомлённость",
)

_CONTEXT_WINDOW = 55  # characters around keyword to inspect


def _normalize_text(text: str) -> str:
    return (text or "").lower()


def _get_context(normalized_text: str, keyword: str) -> str:
    idx = normalized_text.find(keyword)
    if idx == -1:
        return ""
    start = max(0, idx - _CONTEXT_WINDOW)
    end = min(len(normalized_text), idx + len(keyword) + _CONTEXT_WINDOW)
    return normalized_text[start:end]


def _is_false_positive(normalized_text: str, keyword: str) -> bool:
    ctx = _get_context(normalized_text, keyword)
    return any(marker in ctx for marker in _NEGATION_MARKERS)


def _extract_threat_indicators(text: str) -> dict[str, list[str]]:
    normalized = _normalize_text(text)
    found: dict[str, list[str]] = {"high_risk": [], "medium_risk": [], "analyst": []}
    for category, keywords in THREAT_KEYWORDS.items():
        for kw in keywords:
            if kw not in normalized:
                continue
            # High-risk keywords are never negated (malware, exploit → always flag)
            if category == "high_risk":
                found[category].append(kw)
                continue
            if not _is_false_positive(normalized, kw):
                found[category].append(kw)
    return found


def _detect_privacy_tools(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return [tool for tool in PRIVACY_TOOLS if tool in normalized]


def _detect_exposed_pii(text: str) -> list[str]:
    matched: list[str] = []
    normalized = _normalize_text(text)
    for signal in EXPOSURE_SIGNALS:
        if signal in normalized:
            matched.append(signal)
    for pattern in SUSPICIOUS_BIO_PATTERNS:
        if pattern.search(text or ""):
            matched.append(pattern.pattern)
    return matched


def _classify_risk(indicators: dict[str, list[str]], site_list: str) -> str:
    sites = _normalize_text(site_list)
    if indicators["high_risk"] or any(s in sites for s in HIGH_RISK_SITES):
        return "high"
    if indicators["medium_risk"]:
        return "medium"
    if indicators["analyst"] or any(s in sites for s in PROFESSIONAL_SECURITY_SITES):
        return "analyst"
    return "low"


def _opsec_score(profile: dict[str, Any]) -> tuple[int, list[str]]:
    score = 50
    notes: list[str] = []

    bio = str(profile.get("bio") or "")
    username = str(profile.get("username") or "")
    has_photo = bool(profile.get("has_photo") or profile.get("photo_path", "").strip())
    site_count = int(profile.get("site_count") or 0)
    group_count = int(profile.get("group_count") or 0)
    osint_score = int(profile.get("osint_score") or 0)
    site_list = str(profile.get("site_list") or "")

    # High digital footprint = poor OPSEC
    if osint_score >= 65:
        score -= 20
        notes.append("высокий osint_score — широкий цифровой след")
    if site_count >= 5:
        score -= 15
        notes.append(f"найдено {site_count} внешних аккаунтов")
    if site_count >= 10:
        score -= 10
        notes.append("более 10 внешних аккаунтов — крайне высокое раскрытие")
    if has_photo:
        score -= 8
        notes.append("публичное фото профиля")
    if group_count >= 5:
        score -= 10
        notes.append(f"участие в {group_count} Telegram-группах")

    # PII in bio = very poor OPSEC
    exposed = _detect_exposed_pii(bio)
    if exposed:
        score -= 20
        notes.append(f"персональные данные в bio: {len(exposed)} признаков")

    # Privacy tools = good OPSEC
    privacy = _detect_privacy_tools(bio + " " + username)
    if privacy:
        score += 15
        notes.append(f"признаки использования privacy-инструментов: {', '.join(privacy[:3])}")

    # Minimal profile = high OPSEC
    if not bio.strip():
        score += 10
        notes.append("нет bio — минимальная самораскрытость")
    if not username.strip():
        score += 10
        notes.append("нет username — скрытый профиль")
    if not has_photo:
        score += 8
        notes.append("нет фото профиля")

    # Professional security sites = elevated awareness
    sites_lower = site_list.lower()
    if any(s in sites_lower for s in PROFESSIONAL_SECURITY_SITES):
        score += 10
        notes.append("профиль на bug-bounty / CTF платформах")

    return max(0, min(100, score)), notes


def analyze_profile(profile: dict[str, Any]) -> dict[str, Any]:
    bio = str(profile.get("bio") or "")
    username = str(profile.get("username") or "")
    site_list = str(profile.get("site_list") or "")
    groups = str(profile.get("group_name") or "")

    combined_text = " ".join([bio, username, groups])
    indicators = _extract_threat_indicators(combined_text)
    risk_level = _classify_risk(indicators, site_list)
    opsec, opsec_notes = _opsec_score(profile)
    exposed_pii = _detect_exposed_pii(bio)

    # Check site list for high-risk/professional security sites
    site_lower = site_list.lower()
    dark_sites = [s for s in HIGH_RISK_SITES if s in site_lower]
    sec_sites = [s for s in PROFESSIONAL_SECURITY_SITES if s in site_lower]

    return {
        "risk_level": risk_level,
        "opsec_score": opsec,
        "opsec_notes": opsec_notes,
        "threat_indicators": indicators,
        "all_threat_count": sum(len(v) for v in indicators.values()),
        "high_risk_count": len(indicators["high_risk"]),
        "medium_risk_count": len(indicators["medium_risk"]),
        "analyst_count": len(indicators["analyst"]),
        "exposed_pii_count": len(exposed_pii),
        "dark_sites_found": dark_sites,
        "security_platforms": sec_sites,
    }


def detect_anomalies(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not profiles:
        return []

    site_counts = [int(p.get("site_count") or 0) for p in profiles]
    bio_lengths = [int(p.get("bio_length") or 0) for p in profiles]
    avg_sites = sum(site_counts) / len(site_counts) if site_counts else 0
    avg_bio = sum(bio_lengths) / len(bio_lengths) if bio_lengths else 0

    # Detect shared bio fragments (possible bots/clones)
    bio_map: dict[str, list[int]] = defaultdict(list)
    for p in profiles:
        bio = str(p.get("bio") or "").strip().lower()
        if len(bio) >= 20:
            key = bio[:60]
            bio_map[key].append(int(p.get("user_id") or 0))
    clone_groups = {k: v for k, v in bio_map.items() if len(v) >= 2}

    anomalies: list[dict[str, Any]] = []
    for p in profiles:
        reasons: list[str] = []
        site_count = int(p.get("site_count") or 0)
        bio_length = int(p.get("bio_length") or 0)
        bio = str(p.get("bio") or "").strip().lower()

        if site_count > avg_sites * 3 and site_count >= 8:
            reasons.append(f"аномально много внешних аккаунтов: {site_count} (средн. {avg_sites:.1f})")
        if bio_length > avg_bio * 4 and bio_length >= 200:
            reasons.append(f"аномально длинный bio: {bio_length} символов")
        bio_key = bio[:60] if len(bio) >= 20 else ""
        if bio_key and bio_key in clone_groups and len(clone_groups[bio_key]) >= 2:
            reasons.append(f"bio совпадает ещё у {len(clone_groups[bio_key]) - 1} профилей (возможный клон/бот)")
        sec_result = analyze_profile(p)
        if sec_result["high_risk_count"] >= 2:
            reasons.append(f"высокий риск: {sec_result['high_risk_count']} индикатора угроз")
        if sec_result["exposed_pii_count"] >= 2:
            reasons.append(f"много раскрытых персональных данных в bio: {sec_result['exposed_pii_count']}")

        if reasons:
            anomalies.append({
                "user_id": p.get("user_id"),
                "username": p.get("username") or "[скрыт]",
                "first_name": p.get("first_name") or "",
                "osint_score": p.get("osint_score") or 0,
                "risk_level": sec_result["risk_level"],
                "opsec_score": sec_result["opsec_score"],
                "anomaly_reasons": reasons,
            })

    return sorted(anomalies, key=lambda x: len(x["anomaly_reasons"]), reverse=True)


def get_security_snapshot(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    if not profiles:
        return {
            "total": 0,
            "risk_distribution": {},
            "opsec_distribution": {},
            "top_threats": [],
            "anomalies": [],
            "pii_exposed_count": 0,
            "privacy_tools_count": 0,
        }

    risk_counter: Counter[str] = Counter()
    opsec_buckets = {"0-29 (низкий)": 0, "30-59 (средний)": 0, "60-79 (хороший)": 0, "80-100 (высокий)": 0}
    threat_profiles: list[dict[str, Any]] = []
    pii_count = 0
    privacy_count = 0

    for p in profiles:
        result = analyze_profile(p)
        risk_counter[result["risk_level"]] += 1

        opsec = result["opsec_score"]
        if opsec < 30:
            opsec_buckets["0-29 (низкий)"] += 1
        elif opsec < 60:
            opsec_buckets["30-59 (средний)"] += 1
        elif opsec < 80:
            opsec_buckets["60-79 (хороший)"] += 1
        else:
            opsec_buckets["80-100 (высокий)"] += 1

        if result["exposed_pii_count"] > 0:
            pii_count += 1
        if result["opsec_score"] >= 65 and "privacy" in " ".join(result["opsec_notes"]).lower():
            privacy_count += 1

        if result["risk_level"] in ("high", "medium"):
            threat_profiles.append({
                "user_id": p.get("user_id"),
                "username": p.get("username") or "[скрыт]",
                "first_name": p.get("first_name") or "",
                "risk_level": result["risk_level"],
                "opsec_score": result["opsec_score"],
                "threat_count": result["all_threat_count"],
                "indicators": result["threat_indicators"],
                "osint_score": p.get("osint_score") or 0,
            })

    threat_profiles.sort(key=lambda x: (x["threat_count"], -x["opsec_score"]), reverse=True)
    anomalies = detect_anomalies(profiles)

    return {
        "total": len(profiles),
        "risk_distribution": dict(risk_counter),
        "opsec_distribution": opsec_buckets,
        "top_threats": threat_profiles[:15],
        "anomalies": anomalies[:10],
        "pii_exposed_count": pii_count,
        "privacy_tools_count": privacy_count,
    }


_BOT_PATTERNS = [
    re.compile(r"^[a-z]{2,6}\d{4,10}$"),
    re.compile(r"^[a-z]+_\d{4,}$"),
    re.compile(r"^\d{6,15}$"),
    re.compile(r"^[a-z]{1,3}\d{3,}[a-z]{0,2}$"),
    re.compile(r"^user\d+$"),
]


def _username_looks_bot(username: str) -> bool:
    u = (username or "").lower().strip("@")
    return bool(u) and any(p.match(u) for p in _BOT_PATTERNS)


def detect_coordinated_behavior(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect patterns suggesting coordinated inauthentic behavior.

    Checks:
    - High ratio of bot-like usernames in the dataset
    - Clusters of profiles with identical bio fragments (already in detect_anomalies)
    - Username prefix families (many profiles share a common prefix + digits)
    """
    if not profiles:
        return {"bot_username_count": 0, "bot_ratio": 0.0, "prefix_families": [], "verdict": "insufficient data"}

    total = len(profiles)
    bot_users = [p for p in profiles if _username_looks_bot(p.get("username") or "")]
    bot_ratio = len(bot_users) / total

    # Prefix family detection: group usernames by 4-char prefix
    prefix_map: dict[str, list[str]] = defaultdict(list)
    for p in profiles:
        u = (p.get("username") or "").lower().strip("@")
        if len(u) >= 4 and not u.isdigit():
            prefix_map[u[:4]].append(u)

    prefix_families = [
        {"prefix": prefix, "count": len(members), "sample": members[:5]}
        for prefix, members in sorted(prefix_map.items(), key=lambda x: -len(x[1]))
        if len(members) >= 3
    ][:10]

    if bot_ratio > 0.40:
        verdict = "высокая вероятность скоординированной сети ботов"
    elif bot_ratio > 0.20:
        verdict = "умеренный уровень подозрительных аккаунтов"
    elif prefix_families and prefix_families[0]["count"] >= 5:
        verdict = "обнаружены семейства схожих username — возможна координация"
    else:
        verdict = "признаков скоординированного поведения не обнаружено"

    return {
        "bot_username_count": len(bot_users),
        "bot_ratio": round(bot_ratio, 3),
        "bot_sample": [p.get("username") or "" for p in bot_users[:8]],
        "prefix_families": prefix_families,
        "verdict": verdict,
    }


def export_security_report(profiles: list[dict[str, Any]], path: Path | None = None) -> Path:
    target = path or BASE_DIR / "security_report.md"
    snapshot = get_security_snapshot(profiles)

    risk_lines = "\n".join(
        f"- {level}: {count}" for level, count in sorted(snapshot["risk_distribution"].items())
    ) or "- нет данных"

    opsec_lines = "\n".join(
        f"- {bucket}: {count}" for bucket, count in snapshot["opsec_distribution"].items()
    )

    threats_lines = "\n".join(
        "- @{username} ({name}): риск={risk}, opsec={opsec}, "
        "угроз={count}".format(
            username=t["username"],
            name=t["first_name"],
            risk=t["risk_level"],
            opsec=t["opsec_score"],
            count=t["threat_count"],
        )
        for t in snapshot["top_threats"][:10]
    ) or "- не обнаружено"

    anomalies_lines = "\n".join(
        "- @{username}: {reasons}".format(
            username=a["username"],
            reasons="; ".join(a["anomaly_reasons"]),
        )
        for a in snapshot["anomalies"][:10]
    ) or "- аномалий не обнаружено"

    coord = detect_coordinated_behavior(profiles)
    coord_lines = (
        f"- Бот-подобных username: {coord['bot_username_count']} из {snapshot['total']} "
        f"({coord['bot_ratio']*100:.1f}%)\n"
        f"- Вердикт: {coord['verdict']}\n"
        + (
            "- Примеры подозрительных: " + ", ".join(coord["bot_sample"][:6])
            if coord["bot_sample"] else ""
        )
    )

    content = f"""# Security Analysis Report

## Обзор набора данных

- Всего профилей проанализировано: {snapshot['total']}
- Профилей с раскрытыми персональными данными (PII): {snapshot['pii_exposed_count']}
- Профилей с признаками privacy-инструментов: {snapshot['privacy_tools_count']}

## Распределение уровней угроз

{risk_lines}

Уровни:
- **high** — ключевые слова высокой опасности (malware, exploit, darkweb, C2)
- **medium** — pentest / hacking / phishing / osint-инструменты
- **analyst** — легитимные специалисты по безопасности (bug bounty, SOC, forensics)
- **low** — угроз не обнаружено

Детектор использует контекстный анализ (окно ±55 символов): ключевое слово в контексте
«защита от», «researcher», «учебный курс» не приводит к повышению уровня угрозы.

## Распределение OPSEC-баллов

{opsec_lines}

OPSEC (Operational Security) — балл оценивает уровень оперативной безопасности:
высокий балл = минимальный цифровой след + использование privacy-инструментов.

## Скоординированное поведение

{coord_lines}

## Топ профилей по угрозе

{threats_lines}

## Обнаруженные аномалии

{anomalies_lines}

## Методология

1. **Threat detection** — трёхуровневая таксономия ключевых слов с контекстным анализом
2. **OPSEC score** — взвешенная оценка цифрового следа, PII, privacy-инструментов
3. **Coordinated behavior** — анализ username-паттернов, кластеры семейств имён
4. **Anomaly detection** — клоны по bio, аномальный размер footprint, раскрытые PII
5. **Site analysis** — проверка Sherlock/Snoop результатов на dark-web и CTF/bug-bounty платформы
"""
    target.write_text(content, encoding="utf-8")
    return target
