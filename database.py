from __future__ import annotations

import csv
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "osint_database.db"
RUNTIME_DIR = Path(tempfile.gettempdir()) / "kursa4_osint_runtime"
RUNTIME_DB_PATH = RUNTIME_DIR / "osint_database_runtime.db"
AVATARS_DIR = BASE_DIR / "avatars"
BASELINE_DATASET_PATH = BASE_DIR / "nlp_dataset.csv"
ENRICHED_DATASET_PATH = BASE_DIR / "nlp_dataset_enriched.csv"
OSINT_REPORT_PATH = BASE_DIR / "osint_report.csv"
SUMMARY_REPORT_PATH = BASE_DIR / "summary_report.md"
PROFILE_REPORTS_DIR = BASE_DIR / "profile_reports"
ACTIVE_DB_PATH = DB_PATH
ACTIVE_DB_URI = False
DB_READY = False
MEMORY_DB_URI = "file:osint_runtime?mode=memory&cache=shared"
MEMORY_KEEPALIVE: sqlite3.Connection | None = None

def utcnow_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(ACTIVE_DB_PATH, timeout=30, uri=ACTIVE_DB_URI)
    conn.row_factory = sqlite3.Row
    return conn

def _seed_from_baseline_csv(conn: sqlite3.Connection) -> None:
    if not BASELINE_DATASET_PATH.exists():
        return

    count_row = conn.execute("SELECT COUNT(*) AS count_value FROM profiles").fetchone()
    if count_row["count_value"] > 0:
        return

    with BASELINE_DATASET_PATH.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj, delimiter=";")
        for row in reader:
            user_id = int(row["user_id"])
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (user_id, first_name, username, bio, photo_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    row.get("first_name", ""),
                    row.get("username", ""),
                    row.get("bio", ""),
                    row.get("photo_path", ""),
                ),
            )
            groups = [item.strip() for item in row.get("group_name", "").split("|") if item.strip()]
            for group_name in groups:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO user_groups (user_id, group_name, parsed_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, group_name, utcnow_text()),
                )
            if not row.get("username", "").strip():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO username_checks (user_id, username, status, checked_at, found_count, error_text)
                    VALUES (?, ?, 'skipped', ?, 0, NULL)
                    """,
                    (user_id, "", utcnow_text()),
                )
    conn.commit()

def _migrate_social_accounts_source_unique(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'social_accounts'
        """
    ).fetchone()
    table_sql = (row["sql"] if row else "") or ""
    normalized_sql = table_sql.lower().replace(" ", "").replace("\n", "")
    if "unique(user_id,site_name,profile_url)" not in normalized_sql:
        return

    conn.execute("ALTER TABLE social_accounts RENAME TO social_accounts_old")
    conn.execute(
        """
        CREATE TABLE social_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            site_name TEXT NOT NULL,
            profile_url TEXT NOT NULL,
            username TEXT,
            source TEXT NOT NULL DEFAULT 'sherlock',
            checked_at TEXT NOT NULL,
            UNIQUE(user_id, site_name, profile_url, source)
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO social_accounts
            (user_id, site_name, profile_url, username, source, checked_at)
        SELECT
            user_id,
            site_name,
            profile_url,
            username,
            COALESCE(NULLIF(source, ''), 'sherlock'),
            checked_at
        FROM social_accounts_old
        """
    )
    conn.execute("DROP TABLE social_accounts_old")

def _initialize_schema(path: Path, seed_from_csv: bool) -> None:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                bio TEXT,
                photo_path TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                group_name TEXT NOT NULL,
                parsed_at TEXT NOT NULL,
                UNIQUE(user_id, group_name)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS username_checks (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                status TEXT NOT NULL,
                checked_at TEXT,
                found_count INTEGER NOT NULL DEFAULT 0,
                error_text TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS enrichment_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                checked_at TEXT,
                found_count INTEGER NOT NULL DEFAULT 0,
                error_text TEXT,
                UNIQUE(user_id, tool_name)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS social_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                site_name TEXT NOT NULL,
                profile_url TEXT NOT NULL,
                username TEXT,
                source TEXT NOT NULL DEFAULT 'sherlock',
                checked_at TEXT NOT NULL,
                UNIQUE(user_id, site_name, profile_url, source)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_names (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                recorded_at TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, name)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS message_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                interaction_type TEXT NOT NULL,
                group_id INTEGER,
                group_name TEXT,
                recorded_at TEXT DEFAULT (datetime('now')),
                UNIQUE(from_user_id, to_user_id, interaction_type, group_id)
            )
            """
        )
        _migrate_social_accounts_source_unique(conn)
        conn.commit()
        if seed_from_csv:
            _seed_from_baseline_csv(conn)
    finally:
        conn.close()

def _initialize_memory_schema(seed_from_csv: bool) -> None:
    global MEMORY_KEEPALIVE

    MEMORY_KEEPALIVE = sqlite3.connect(MEMORY_DB_URI, uri=True, timeout=30)
    MEMORY_KEEPALIVE.row_factory = sqlite3.Row
    cursor = MEMORY_KEEPALIVE.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            bio TEXT,
            photo_path TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            parsed_at TEXT NOT NULL,
            UNIQUE(user_id, group_name)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS username_checks (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            status TEXT NOT NULL,
            checked_at TEXT,
            found_count INTEGER NOT NULL DEFAULT 0,
            error_text TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS enrichment_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            tool_name TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT,
            found_count INTEGER NOT NULL DEFAULT 0,
            error_text TEXT,
            UNIQUE(user_id, tool_name)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS social_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            site_name TEXT NOT NULL,
            profile_url TEXT NOT NULL,
            username TEXT,
            source TEXT NOT NULL DEFAULT 'sherlock',
            checked_at TEXT NOT NULL,
            UNIQUE(user_id, site_name, profile_url, source)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS social_account_reviews (
            account_id INTEGER PRIMARY KEY,
            review_status TEXT NOT NULL DEFAULT 'pending',
            review_note TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    _migrate_social_accounts_source_unique(MEMORY_KEEPALIVE)
    MEMORY_KEEPALIVE.commit()
    if seed_from_csv:
        _seed_from_baseline_csv(MEMORY_KEEPALIVE)

def init_db() -> None:
    global ACTIVE_DB_PATH, ACTIVE_DB_URI, DB_READY

    if DB_READY:
        return

    AVATARS_DIR.mkdir(exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        ACTIVE_DB_PATH = DB_PATH
        ACTIVE_DB_URI = False
        _initialize_schema(DB_PATH, seed_from_csv=False)
    except sqlite3.OperationalError:
        try:
            ACTIVE_DB_PATH = RUNTIME_DB_PATH
            ACTIVE_DB_URI = False
            _initialize_schema(RUNTIME_DB_PATH, seed_from_csv=True)
        except sqlite3.OperationalError:
            ACTIVE_DB_PATH = MEMORY_DB_URI
            ACTIVE_DB_URI = True
            _initialize_memory_schema(seed_from_csv=True)
    DB_READY = True



def get_existing_user_ids() -> set[int]:
    init_db()
    with get_connection() as conn:
        return {row["user_id"] for row in conn.execute("SELECT user_id FROM profiles")}

def save_profile(
    user_id: int,
    first_name: str | None,
    username: str | None,
    bio: str | None,
    photo_path: str | None,
) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO profiles (user_id, first_name, username, bio, photo_path)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = CASE
                    WHEN excluded.first_name IS NULL OR excluded.first_name = ''
                    THEN profiles.first_name
                    ELSE excluded.first_name
                END,
                username = CASE
                    WHEN excluded.username IS NULL OR excluded.username = ''
                    THEN profiles.username
                    ELSE excluded.username
                END,
                bio = CASE
                    WHEN excluded.bio IS NULL OR excluded.bio = ''
                    THEN profiles.bio
                    ELSE excluded.bio
                END,
                photo_path = CASE
                    WHEN excluded.photo_path IS NULL OR excluded.photo_path = ''
                    THEN profiles.photo_path
                    ELSE excluded.photo_path
                END
            """,
            (user_id, first_name or "", username or "", bio or "", photo_path or ""),
        )
        if first_name and first_name.strip():
            conn.execute(
                "INSERT OR IGNORE INTO profile_names (user_id, name) VALUES (?, ?)",
                (user_id, first_name.strip()),
            )
        conn.commit()

def save_interaction(
    from_user_id: int,
    to_user_id: int,
    interaction_type: str,
    group_id: int | None = None,
    group_name: str | None = None,
) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO message_interactions
                (from_user_id, to_user_id, interaction_type, group_id, group_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (from_user_id, to_user_id, interaction_type, group_id, group_name),
        )
        conn.commit()

def get_interactions(user_id: int) -> list[dict]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT from_user_id, to_user_id, interaction_type, group_name
            FROM message_interactions
            WHERE from_user_id = ? OR to_user_id = ?
            """,
            (user_id, user_id),
        ).fetchall()
    return [dict(r) for r in rows]

def get_profile_names(user_id: int) -> list[str]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM profile_names WHERE user_id = ? ORDER BY recorded_at",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]

def link_user_group(user_id: int, group_name: str, parsed_at: str | None = None) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_groups (user_id, group_name, parsed_at)
            VALUES (?, ?, ?)
            """,
            (user_id, group_name, parsed_at or utcnow_text()),
        )
        conn.commit()

def queue_username_check_if_needed(user_id: int, username: str) -> bool:
    init_db()
    username = (username or "").strip()
    if not username:
        mark_username_skipped(user_id, "")
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT username, status
            FROM username_checks
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        should_queue = (
            row is None
            or row["username"] != username
            or row["status"] in {"error", "skipped"}
        )
        if not should_queue:
            return False

        conn.execute(
            """
            INSERT INTO username_checks (user_id, username, status, checked_at, found_count, error_text)
            VALUES (?, ?, 'pending', NULL, 0, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                status = 'pending',
                checked_at = NULL,
                found_count = 0,
                error_text = NULL
            """,
            (user_id, username),
        )
        conn.commit()
        return True

def mark_username_skipped(user_id: int, username: str | None) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO username_checks (user_id, username, status, checked_at, found_count, error_text)
            VALUES (?, ?, 'skipped', ?, 0, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                status = 'skipped',
                checked_at = excluded.checked_at,
                found_count = 0,
                error_text = NULL
            """,
            (user_id, username or "", utcnow_text()),
        )
        conn.commit()

def mark_username_done(user_id: int, username: str, found_count: int) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO username_checks (user_id, username, status, checked_at, found_count, error_text)
            VALUES (?, ?, 'done', ?, ?, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                status = 'done',
                checked_at = excluded.checked_at,
                found_count = excluded.found_count,
                error_text = NULL
            """,
            (user_id, username, utcnow_text(), found_count),
        )
        conn.commit()

def mark_username_error(user_id: int, username: str, error_text: str) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO username_checks (user_id, username, status, checked_at, found_count, error_text)
            VALUES (?, ?, 'error', ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                status = 'error',
                checked_at = excluded.checked_at,
                found_count = 0,
                error_text = excluded.error_text
            """,
            (user_id, username, utcnow_text(), error_text[:1000]),
        )
        conn.commit()

def queue_enrichment_check_if_needed(user_id: int, username: str, tool_name: str) -> bool:
    init_db()
    username = (username or "").strip()
    tool_name = (tool_name or "").strip().lower()
    if not username or not tool_name:
        if tool_name:
            mark_enrichment_skipped(user_id, username, tool_name)
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT username, status
            FROM enrichment_checks
            WHERE user_id = ? AND tool_name = ?
            """,
            (user_id, tool_name),
        ).fetchone()
        should_queue = (
            row is None
            or row["username"] != username
            or row["status"] in {"error", "skipped"}
        )
        if not should_queue:
            return False

        conn.execute(
            """
            INSERT INTO enrichment_checks
                (user_id, username, tool_name, status, checked_at, found_count, error_text)
            VALUES (?, ?, ?, 'pending', NULL, 0, NULL)
            ON CONFLICT(user_id, tool_name) DO UPDATE SET
                username = excluded.username,
                status = 'pending',
                checked_at = NULL,
                found_count = 0,
                error_text = NULL
            """,
            (user_id, username, tool_name),
        )
        conn.commit()
        return True

def mark_enrichment_skipped(user_id: int, username: str | None, tool_name: str) -> None:
    init_db()
    tool_name = (tool_name or "").strip().lower()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO enrichment_checks
                (user_id, username, tool_name, status, checked_at, found_count, error_text)
            VALUES (?, ?, ?, 'skipped', ?, 0, NULL)
            ON CONFLICT(user_id, tool_name) DO UPDATE SET
                username = excluded.username,
                status = 'skipped',
                checked_at = excluded.checked_at,
                found_count = 0,
                error_text = NULL
            """,
            (user_id, username or "", tool_name, utcnow_text()),
        )
        conn.commit()

def mark_enrichment_done(user_id: int, username: str, tool_name: str, found_count: int) -> None:
    init_db()
    tool_name = (tool_name or "").strip().lower()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO enrichment_checks
                (user_id, username, tool_name, status, checked_at, found_count, error_text)
            VALUES (?, ?, ?, 'done', ?, ?, NULL)
            ON CONFLICT(user_id, tool_name) DO UPDATE SET
                username = excluded.username,
                status = 'done',
                checked_at = excluded.checked_at,
                found_count = excluded.found_count,
                error_text = NULL
            """,
            (user_id, username, tool_name, utcnow_text(), found_count),
        )
        conn.commit()

def mark_enrichment_error(user_id: int, username: str, tool_name: str, error_text: str) -> None:
    init_db()
    tool_name = (tool_name or "").strip().lower()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO enrichment_checks
                (user_id, username, tool_name, status, checked_at, found_count, error_text)
            VALUES (?, ?, ?, 'error', ?, 0, ?)
            ON CONFLICT(user_id, tool_name) DO UPDATE SET
                username = excluded.username,
                status = 'error',
                checked_at = excluded.checked_at,
                found_count = 0,
                error_text = excluded.error_text
            """,
            (user_id, username, tool_name, utcnow_text(), error_text[:1000]),
        )
        conn.commit()

def save_social_accounts(
    user_id: int,
    username: str,
    accounts: Iterable[dict[str, str]],
    source: str = "sherlock",
) -> int:
    init_db()
    checked_at = utcnow_text()
    unique_accounts: dict[tuple[str, str], dict[str, str]] = {}
    for account in accounts:
        site_name = (account.get("site_name") or "").strip()
        profile_url = (account.get("profile_url") or "").strip()
        if not site_name or not profile_url:
            continue
        unique_accounts[(site_name.lower(), profile_url)] = {
            "site_name": site_name,
            "profile_url": profile_url,
            "username": (account.get("username") or username or "").strip(),
        }

    with get_connection() as conn:
        conn.execute(
            "DELETE FROM social_accounts WHERE user_id = ? AND source = ?",
            (user_id, source),
        )
        for account in unique_accounts.values():
            conn.execute(
                """
                INSERT OR IGNORE INTO social_accounts
                    (user_id, site_name, profile_url, username, source, checked_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    account["site_name"],
                    account["profile_url"],
                    account["username"],
                    source,
                    checked_at,
                ),
            )
        conn.commit()
    return len(unique_accounts)

def list_pending_username_checks(limit: int = 100) -> list[dict]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT user_id, username
            FROM username_checks
            WHERE status = 'pending' AND username IS NOT NULL AND TRIM(username) <> ''
            ORDER BY user_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]

def list_pending_enrichment_checks(tool_name: str, limit: int = 100) -> list[dict]:
    init_db()
    tool_name = (tool_name or "").strip().lower()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT user_id, username, tool_name
            FROM enrichment_checks
            WHERE tool_name = ?
              AND status = 'pending'
              AND username IS NOT NULL
              AND TRIM(username) <> ''
            ORDER BY user_id
            LIMIT ?
            """,
            (tool_name, limit),
        ).fetchall()
    return [dict(row) for row in rows]

def get_dashboard_stats() -> dict[str, int]:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM profiles) AS profiles,
                (SELECT COUNT(*) FROM username_checks WHERE status = 'pending') AS queued_checks,
                (SELECT COUNT(*) FROM username_checks WHERE status = 'done') AS completed_checks,
                (SELECT COUNT(*) FROM enrichment_checks WHERE tool_name = 'snoop' AND status = 'pending') AS queued_snoop_checks,
                (SELECT COUNT(*) FROM enrichment_checks WHERE tool_name = 'snoop' AND status = 'done') AS completed_snoop_checks,
                (SELECT COUNT(*) FROM enrichment_checks WHERE tool_name = 'maigret' AND status = 'pending') AS queued_maigret_checks,
                (SELECT COUNT(*) FROM enrichment_checks WHERE tool_name = 'maigret' AND status = 'done') AS completed_maigret_checks,
                (SELECT COUNT(*) FROM social_accounts) AS social_accounts
            """
        ).fetchone()
    return dict(row)

def _summary_query() -> str:
    return """
        WITH group_data AS (
            SELECT
                user_id,
                REPLACE(GROUP_CONCAT(DISTINCT group_name), ',', '|') AS group_name,
                COUNT(DISTINCT group_name) AS group_count,
                MAX(parsed_at) AS last_parsed_at
            FROM user_groups
            GROUP BY user_id
        ),
        social_data AS (
            SELECT
                user_id,
                COUNT(*) AS site_count,
                REPLACE(GROUP_CONCAT(DISTINCT site_name), ',', '|') AS site_list,
                MAX(CASE WHEN LOWER(site_name) = 'github' THEN 1 ELSE 0 END) AS has_github,
                MAX(CASE WHEN LOWER(site_name) = 'linkedin' THEN 1 ELSE 0 END) AS has_linkedin,
                MAX(CASE WHEN LOWER(site_name) = 'behance' THEN 1 ELSE 0 END) AS has_behance,
                MAX(CASE WHEN LOWER(site_name) IN ('x', 'twitter') THEN 1 ELSE 0 END) AS has_x,
                MAX(CASE WHEN LOWER(site_name) = 'reddit' THEN 1 ELSE 0 END) AS has_reddit
            FROM social_accounts
            GROUP BY user_id
        ),
        snoop_data AS (
            SELECT
                user_id,
                status,
                found_count,
                error_text,
                checked_at
            FROM enrichment_checks
            WHERE tool_name = 'snoop'
        ),
        maigret_data AS (
            SELECT
                user_id,
                status,
                found_count,
                error_text,
                checked_at
            FROM enrichment_checks
            WHERE tool_name = 'maigret'
        )
        SELECT
            p.user_id,
            p.first_name,
            p.username,
            COALESCE(p.bio, '') AS bio,
            COALESCE(p.photo_path, '') AS photo_path,
            COALESCE(g.group_name, '') AS group_name,
            COALESCE(g.group_count, 0) AS group_count,
            COALESCE(g.last_parsed_at, '') AS last_parsed_at,
            LENGTH(TRIM(COALESCE(p.bio, ''))) AS bio_length,
            CASE WHEN TRIM(COALESCE(p.photo_path, '')) <> '' THEN 1 ELSE 0 END AS has_photo,
            COALESCE(s.site_count, 0) AS site_count,
            COALESCE(s.site_list, '') AS site_list,
            COALESCE(s.has_github, 0) AS has_github,
            COALESCE(s.has_linkedin, 0) AS has_linkedin,
            COALESCE(s.has_behance, 0) AS has_behance,
            COALESCE(s.has_x, 0) AS has_x,
            COALESCE(s.has_reddit, 0) AS has_reddit,
            COALESCE(uc.status, '') AS sherlock_status,
            COALESCE(uc.found_count, 0) AS sherlock_found_count,
            COALESCE(uc.error_text, '') AS sherlock_error_text,
            COALESCE(uc.checked_at, '') AS sherlock_checked_at,
            COALESCE(sn.status, '') AS snoop_status,
            COALESCE(sn.found_count, 0) AS snoop_found_count,
            COALESCE(sn.error_text, '') AS snoop_error_text,
            COALESCE(sn.checked_at, '') AS snoop_checked_at,
            COALESCE(mg.status, '') AS maigret_status,
            COALESCE(mg.found_count, 0) AS maigret_found_count,
            COALESCE(mg.error_text, '') AS maigret_error_text,
            COALESCE(mg.checked_at, '') AS maigret_checked_at,
            (
                CASE WHEN TRIM(COALESCE(p.username, '')) <> '' THEN 15 ELSE 0 END +
                CASE WHEN TRIM(COALESCE(p.bio, '')) <> '' THEN 20 ELSE 0 END +
                CASE WHEN TRIM(COALESCE(p.photo_path, '')) <> '' THEN 10 ELSE 0 END +
                CASE
                    WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) >= 120 THEN 15
                    WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) >= 40 THEN 10
                    WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) > 0 THEN 5
                    ELSE 0
                END +
                MIN(COALESCE(g.group_count, 0) * 10, 25) +
                MIN(COALESCE(s.site_count, 0) * 15, 30)
            ) AS osint_score,
            CASE
                WHEN (
                    CASE WHEN TRIM(COALESCE(p.username, '')) <> '' THEN 15 ELSE 0 END +
                    CASE WHEN TRIM(COALESCE(p.bio, '')) <> '' THEN 20 ELSE 0 END +
                    CASE WHEN TRIM(COALESCE(p.photo_path, '')) <> '' THEN 10 ELSE 0 END +
                    CASE
                        WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) >= 120 THEN 15
                        WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) >= 40 THEN 10
                        WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) > 0 THEN 5
                        ELSE 0
                    END +
                    MIN(COALESCE(g.group_count, 0) * 10, 25) +
                    MIN(COALESCE(s.site_count, 0) * 15, 30)
                ) >= 65 THEN 'high'
                WHEN (
                    CASE WHEN TRIM(COALESCE(p.username, '')) <> '' THEN 15 ELSE 0 END +
                    CASE WHEN TRIM(COALESCE(p.bio, '')) <> '' THEN 20 ELSE 0 END +
                    CASE WHEN TRIM(COALESCE(p.photo_path, '')) <> '' THEN 10 ELSE 0 END +
                    CASE
                        WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) >= 120 THEN 15
                        WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) >= 40 THEN 10
                        WHEN LENGTH(TRIM(COALESCE(p.bio, ''))) > 0 THEN 5
                        ELSE 0
                    END +
                    MIN(COALESCE(g.group_count, 0) * 10, 25) +
                    MIN(COALESCE(s.site_count, 0) * 15, 30)
                ) >= 40 THEN 'medium'
                ELSE 'low'
            END AS exposure_level
        FROM profiles p
        LEFT JOIN group_data g ON g.user_id = p.user_id
        LEFT JOIN social_data s ON s.user_id = p.user_id
        LEFT JOIN username_checks uc ON uc.user_id = p.user_id
        LEFT JOIN snoop_data sn ON sn.user_id = p.user_id
        LEFT JOIN maigret_data mg ON mg.user_id = p.user_id
    """

def get_analytics_snapshot() -> dict:
    init_db()
    with get_connection() as conn:
        totals = dict(
            conn.execute(
                """
                SELECT
                    COUNT(*) AS profiles,
                    SUM(CASE WHEN TRIM(COALESCE(bio, '')) <> '' THEN 1 ELSE 0 END) AS with_bio,
                    SUM(CASE WHEN TRIM(COALESCE(username, '')) <> '' THEN 1 ELSE 0 END) AS with_username,
                    SUM(CASE WHEN TRIM(COALESCE(photo_path, '')) <> '' THEN 1 ELSE 0 END) AS with_photo
                FROM profiles
                """
            ).fetchone()
        )
        top_groups = [
            dict(row)
            for row in conn.execute(
                """
                SELECT group_name, COUNT(*) AS count_value
                FROM user_groups
                GROUP BY group_name
                ORDER BY count_value DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        sherlock_statuses = [
            dict(row)
            for row in conn.execute(
                """
                SELECT COALESCE(NULLIF(status, ''), 'not_started') AS status, COUNT(*) AS count_value
                FROM username_checks
                GROUP BY COALESCE(NULLIF(status, ''), 'not_started')
                ORDER BY count_value DESC
                """
            ).fetchall()
        ]
        top_sites = [
            dict(row)
            for row in conn.execute(
                """
                SELECT site_name, COUNT(*) AS count_value
                FROM social_accounts
                GROUP BY site_name
                ORDER BY count_value DESC
                LIMIT 10
                """
            ).fetchall()
        ]

        rows = conn.execute(_summary_query()).fetchall()

    score_buckets = {"0-24": 0, "25-49": 0, "50-74": 0, "75-100": 0}
    bio_buckets = {"0": 0, "1-40": 0, "41-120": 0, "121+": 0}
    exposure_levels = {"low": 0, "medium": 0, "high": 0}
    for row in rows:
        score = int(row["osint_score"] or 0)
        bio_length = int(row["bio_length"] or 0)
        exposure_levels[row["exposure_level"]] = exposure_levels.get(row["exposure_level"], 0) + 1

        if score < 25:
            score_buckets["0-24"] += 1
        elif score < 50:
            score_buckets["25-49"] += 1
        elif score < 75:
            score_buckets["50-74"] += 1
        else:
            score_buckets["75-100"] += 1

        if bio_length == 0:
            bio_buckets["0"] += 1
        elif bio_length <= 40:
            bio_buckets["1-40"] += 1
        elif bio_length <= 120:
            bio_buckets["41-120"] += 1
        else:
            bio_buckets["121+"] += 1

    return {
        "totals": totals,
        "top_groups": top_groups,
        "sherlock_statuses": sherlock_statuses,
        "top_sites": top_sites,
        "score_buckets": score_buckets,
        "bio_buckets": bio_buckets,
        "exposure_levels": exposure_levels,
    }

def get_search_dataset() -> list[dict]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            _summary_query()
            + """
            WHERE TRIM(COALESCE(p.bio, '')) <> ''
            ORDER BY p.user_id
            """
        ).fetchall()
    return [dict(row) for row in rows]



def list_user_connections() -> list[dict]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.first_name, p.username, ug.group_name, ug.parsed_at
            FROM profiles p
            JOIN user_groups ug ON p.user_id = ug.user_id
            ORDER BY ug.parsed_at DESC, p.user_id
            """
        ).fetchall()
    return [dict(row) for row in rows]

def get_profile_card(user_id: int) -> dict:
    init_db()
    from identity_matcher import IdentityMatcher

    with get_connection() as conn:
        _ensure_social_account_reviews_table(conn)
        profile_row = conn.execute(
            _summary_query() + " WHERE p.user_id = ?",
            (user_id,),
        ).fetchone()
        if profile_row is None:
            raise ValueError(f"Profile {user_id} not found")

        group_rows = conn.execute(
            """
            SELECT group_name, parsed_at
            FROM user_groups
            WHERE user_id = ?
            ORDER BY group_name
            """,
            (user_id,),
        ).fetchall()

        social_rows = conn.execute(
            """
            SELECT
                sa.id,
                sa.site_name,
                sa.profile_url,
                sa.username,
                sa.source,
                sa.checked_at,
                COALESCE(sr.review_status, 'pending') AS review_status,
                COALESCE(sr.review_note, '') AS review_note
            FROM social_accounts sa
            LEFT JOIN social_account_reviews sr ON sr.account_id = sa.id
            WHERE sa.user_id = ?
            ORDER BY sa.site_name
            """,
            (user_id,),
        ).fetchall()

    profile = dict(profile_row)
    matcher = IdentityMatcher()
    social_accounts = matcher.match_many(profile, [dict(row) for row in social_rows])
    for account in social_accounts:
        percent = int(account.get("same_person_percent") or 0)
        account["confidence_score"] = percent
        if percent >= 70:
            account["confidence_level"] = "probable"
        elif percent >= 40:
            account["confidence_level"] = "weak"
        else:
            account["confidence_level"] = "unverified"
    return {
        "profile": profile,
        "groups": [dict(row) for row in group_rows],
        "social_accounts": social_accounts,
    }



def get_osint_analysis_snapshot() -> dict:
    init_db()
    with get_connection() as conn:
        top_profiles = [
            dict(row)
            for row in conn.execute(
                _summary_query()
                + """
                ORDER BY osint_score DESC, site_count DESC, group_count DESC, bio_length DESC
                LIMIT 20
                """
            ).fetchall()
        ]
        group_stats = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    ug.group_name,
                    COUNT(DISTINCT ug.user_id) AS user_count,
                    SUM(CASE WHEN TRIM(COALESCE(p.bio, '')) <> '' THEN 1 ELSE 0 END) AS with_bio,
                    SUM(CASE WHEN TRIM(COALESCE(p.username, '')) <> '' THEN 1 ELSE 0 END) AS with_username,
                    SUM(CASE WHEN TRIM(COALESCE(p.photo_path, '')) <> '' THEN 1 ELSE 0 END) AS with_photo
                FROM user_groups ug
                JOIN profiles p ON p.user_id = ug.user_id
                GROUP BY ug.group_name
                ORDER BY user_count DESC
                LIMIT 20
                """
            ).fetchall()
        ]
        multi_group_users = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    p.user_id,
                    p.first_name,
                    p.username,
                    COUNT(DISTINCT ug.group_name) AS group_count,
                    REPLACE(GROUP_CONCAT(DISTINCT ug.group_name), ',', '|') AS groups
                FROM profiles p
                JOIN user_groups ug ON ug.user_id = p.user_id
                GROUP BY p.user_id, p.first_name, p.username
                HAVING COUNT(DISTINCT ug.group_name) > 1
                ORDER BY group_count DESC, p.user_id
                LIMIT 20
                """
            ).fetchall()
        ]
        group_overlaps = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    a.group_name AS group_a,
                    b.group_name AS group_b,
                    COUNT(DISTINCT a.user_id) AS shared_users
                FROM user_groups a
                JOIN user_groups b
                    ON a.user_id = b.user_id
                   AND a.group_name < b.group_name
                GROUP BY a.group_name, b.group_name
                ORDER BY shared_users DESC
                LIMIT 20
                """
            ).fetchall()
        ]

    return {
        "top_profiles": top_profiles,
        "group_stats": group_stats,
        "multi_group_users": multi_group_users,
        "group_overlaps": group_overlaps,
    }

def export_profile_report_markdown(user_id: int, path: Path | None = None) -> Path:
    init_db()
    PROFILE_REPORTS_DIR.mkdir(exist_ok=True)
    data = get_profile_card(user_id)
    profile = data["profile"]
    username = profile["username"] or "hidden"
    target = path or PROFILE_REPORTS_DIR / f"profile_{profile['user_id']}_{username}.md"

    groups = "\n".join(
        f"- @{row['group_name']} (collected: {row['parsed_at']})"
        for row in data["groups"]
    ) or "- No groups"
    social_accounts = "\n".join(
        "- {site}: {url} [{source}] - same-person {score}% ({verdict}); {reason}".format(
            site=row["site_name"],
            url=row["profile_url"],
            source=row["source"],
            score=row.get("same_person_percent", 0),
            verdict=row.get("identity_verdict", "not_scored"),
            reason=row.get("identity_explanation", "no identity score"),
        )
        for row in data["social_accounts"]
    ) or "- No external accounts found"

    content = f"""# OSINT Profile Report

## Identity

- User ID: {profile['user_id']}
- Name: {profile['first_name'] or 'Unknown'}
- Username: @{username if profile['username'] else 'hidden'}
- Photo path: {profile['photo_path'] or 'not available'}

## Bio

{profile['bio'] or 'No bio'}

## Telegram Presence

- Groups count: {profile['group_count']}
- Bio length: {profile['bio_length']}
- Has photo: {bool(profile['has_photo'])}

Groups:
{groups}

## Cross-Platform Footprint

- Sherlock status: {profile['sherlock_status'] or 'not processed'}
- External accounts found: {profile['site_count']}
- Sites: {profile['site_list'] or 'none'}
- Snoop status: {profile['snoop_status'] or 'not processed'}
- Snoop accounts found: {profile['snoop_found_count']}
- Maigret status: {profile['maigret_status'] or 'not processed'}
- Maigret accounts found: {profile['maigret_found_count']}

Accounts:
{social_accounts}

## OSINT Assessment

- OSINT score: {profile['osint_score']}/100
- Exposure level: {profile['exposure_level']}

Analytical note:
The score is based on the amount of open profile information available in the
local dataset: username, bio, avatar, Telegram group presence, and external
accounts found through Sherlock, Snoop, and Maigret.
Maigret can be launched manually as an additional deep username-enrichment check.
"""
    target.write_text(content, encoding="utf-8")
    return target

def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(
            [{field: row.get(field, "") for field in fieldnames} for row in rows]
        )
    return path

def export_baseline_csv(path: Path | None = None) -> Path:
    init_db()
    target = path or BASELINE_DATASET_PATH
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.user_id,
                p.first_name,
                p.username,
                COALESCE(p.bio, '') AS bio,
                COALESCE(p.photo_path, '') AS photo_path,
                COALESCE(REPLACE(GROUP_CONCAT(DISTINCT ug.group_name), ',', '|'), '') AS group_name
            FROM profiles p
            LEFT JOIN user_groups ug ON ug.user_id = p.user_id
            GROUP BY p.user_id, p.first_name, p.username, p.bio, p.photo_path
            ORDER BY p.user_id
            """
        ).fetchall()
    return _write_csv(
        target,
        ["user_id", "first_name", "username", "bio", "photo_path", "group_name"],
        [dict(row) for row in rows],
    )

def export_enriched_csv(path: Path | None = None) -> Path:
    init_db()
    target = path or ENRICHED_DATASET_PATH
    with get_connection() as conn:
        rows = conn.execute(
            _summary_query() + " ORDER BY p.user_id"
        ).fetchall()
    return _write_csv(
        target,
        [
            "user_id",
            "first_name",
            "username",
            "bio",
            "photo_path",
            "group_name",
            "group_count",
            "last_parsed_at",
            "bio_length",
            "has_photo",
            "site_count",
            "site_list",
            "has_github",
            "has_linkedin",
            "has_behance",
            "has_x",
            "has_reddit",
            "sherlock_status",
            "sherlock_found_count",
            "sherlock_error_text",
            "sherlock_checked_at",
            "snoop_status",
            "snoop_found_count",
            "snoop_error_text",
            "snoop_checked_at",
            "maigret_status",
            "maigret_found_count",
            "maigret_error_text",
            "maigret_checked_at",
            "osint_score",
            "exposure_level",
        ],
        [dict(row) for row in rows],
    )

def export_osint_report_csv(path: Path | None = None) -> Path:
    init_db()
    target = path or OSINT_REPORT_PATH
    with get_connection() as conn:
        rows = conn.execute(
            _summary_query() + " ORDER BY site_count DESC, p.user_id"
        ).fetchall()
    return _write_csv(
        target,
        [
            "user_id",
            "first_name",
            "username",
            "group_name",
            "bio",
            "group_count",
            "bio_length",
            "has_photo",
            "site_count",
            "site_list",
            "osint_score",
            "exposure_level",
            "sherlock_status",
            "sherlock_found_count",
            "sherlock_checked_at",
            "snoop_status",
            "snoop_found_count",
            "snoop_checked_at",
            "maigret_status",
            "maigret_found_count",
            "maigret_checked_at",
            "last_parsed_at",
        ],
        [dict(row) for row in rows],
    )

def export_summary_report_markdown(path: Path | None = None) -> Path:
    init_db()
    target = path or SUMMARY_REPORT_PATH
    snapshot = get_analytics_snapshot()
    osint_snapshot = get_osint_analysis_snapshot()
    totals = snapshot["totals"]

    top_groups = "\n".join(
        f"- {row['group_name']}: {row['count_value']}"
        for row in snapshot["top_groups"][:5]
    ) or "- No groups"
    score_buckets = "\n".join(
        f"- {label}: {value}"
        for label, value in snapshot["score_buckets"].items()
    )
    bio_buckets = "\n".join(
        f"- {label}: {value}"
        for label, value in snapshot["bio_buckets"].items()
    )
    exposure_levels = "\n".join(
        f"- {label}: {value}"
        for label, value in snapshot["exposure_levels"].items()
    )
    top_profiles = "\n".join(
        f"- @{row['username'] or 'hidden'}: score {row['osint_score']}, {row['exposure_level']}"
        for row in osint_snapshot["top_profiles"][:5]
    ) or "- No profiles"
    top_group_stats = "\n".join(
        f"- {row['group_name']}: users {row['user_count']}, usernames {row['with_username']}, bios {row['with_bio']}"
        for row in osint_snapshot["group_stats"][:5]
    ) or "- No groups"

    content = f"""# Сводный отчет

## Обзор данных

- Всего профилей: {totals.get('profiles', 0)}
- Профилей с bio: {totals.get('with_bio', 0)}
- Профилей с username: {totals.get('with_username', 0)}
- Профилей с фото: {totals.get('with_photo', 0)}

## Часть 1. Кибербезопасность и OSINT

OSINT-часть собирает открытые Telegram-профили, хранит связи пользователь-группа,
обогащает username через Sherlock/Snoop/Maigret и рассчитывает `osint_score`
и `exposure_level`.

Топ Telegram-групп:
{top_groups}

Распределение OSINT-балла:
{score_buckets}

Распределение уровня цифрового следа:
{exposure_levels}

Топ профилей по OSINT:
{top_profiles}

Покрытие групп:
{top_group_stats}

## Часть 2. Искусственный интеллект и NLP

AI/NLP-часть выполняет семантический и гибридный поиск, классифицирует профили,
использует `models/profile_classifier.joblib` и оценивает найденные внешние
аккаунты через `models/identity_matcher.joblib`.

Распределение длины bio:
{bio_buckets}

## Демонстрация

1. Открыть `app.py` и показать OSINT-карточку профиля.
2. Показать внешние аккаунты и источники Sherlock/Snoop/Maigret.
3. Открыть `streamlit_app.py` и выполнить NLP-запрос.
4. Показать AI-классификацию и same-person score.
5. Экспортировать CSV/Markdown-отчеты.
"""
    target.write_text(content, encoding="utf-8")
    return target


def export_coursework_report_markdown(path: Path | None = None) -> Path:
    return export_summary_report_markdown(path)
