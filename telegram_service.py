from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import database
from config import env_first, load_env_file
from ai_classifier import normalize_username

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError
    from telethon.tl.functions.users import GetFullUserRequest
except ImportError as exc:  
    TelegramClient = None
    FloodWaitError = Exception
    GetFullUserRequest = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

EventCallback = Callable[[dict], None] | None

@dataclass
class CollectionStats:
    new_profiles: int = 0
    existing_profiles: int = 0
    queued_usernames: int = 0
    skipped_usernames: int = 0

class TelegramCollector:
    def __init__(
        self,
        api_id: str,
        api_hash: str,
        session_name: str = "osint_session",
        delay_seconds: float = 1.5,
    ) -> None:
        load_env_file()
        self.api_id = str(api_id or "").strip() or env_first("TELEGRAM_API_ID", "TG_API_ID")
        self.api_hash = str(api_hash or "").strip() or env_first("TELEGRAM_API_HASH", "TG_API_HASH")
        self.session_name = session_name or "osint_session"
        self.delay_seconds = delay_seconds

    def _emit(self, callback: EventCallback, event_type: str, **payload: object) -> None:
        if callback is not None:
            callback({"type": event_type, **payload})

    async def collect_profile(
        self,
        target: str,
        group_name: str = "direct_lookup",
        event_callback: EventCallback = None,
    ) -> dict:
        database.init_db()
        if IMPORT_ERROR is not None:
            raise RuntimeError(
                "Telethon is not installed. Install dependencies from requirements.txt first."
            )
        if not self.api_id or not self.api_hash:
            raise RuntimeError(
                "Telegram API credentials are required. Set TELEGRAM_API_ID and TELEGRAM_API_HASH "
                "(or TG_API_ID and TG_API_HASH), or enter them in the desktop app."
            )
        if not self.api_id.isdigit():
            raise RuntimeError("Telegram API ID must be a number.")

        normalized_target = normalize_username(target)
        if not normalized_target:
            raise ValueError("Telegram profile target is empty.")
        entity_target: str | int = int(normalized_target) if normalized_target.isdigit() else normalized_target

        client = TelegramClient(self.session_name, int(self.api_id), self.api_hash)
        await client.start()
        self._emit(event_callback, "log", message=f"Resolving Telegram profile {target}")

        try:
            user = await client.get_entity(entity_target)
            bio = ""
            try:
                full_user = await client(GetFullUserRequest(id=user))
                bio = full_user.full_user.about or ""
            except FloodWaitError as exc:
                self._emit(
                    event_callback,
                    "log",
                    message=f"Telegram rate limit reached. Sleeping {exc.seconds}s.",
                )
                await asyncio.sleep(exc.seconds)
            except Exception:
                bio = ""

            photo_path = ""
            if getattr(user, "photo", None):
                photo_file = database.AVATARS_DIR / f"{user.id}.jpg"
                photo_path = str(Path("avatars") / f"{user.id}.jpg").replace("\\", "/")
                if not photo_file.exists():
                    try:
                        await client.download_profile_photo(user, file=str(photo_file))
                    except FloodWaitError as exc:
                        self._emit(
                            event_callback,
                            "log",
                            message=f"Photo download rate limit reached. Sleeping {exc.seconds}s.",
                        )
                        await asyncio.sleep(exc.seconds)
                    except Exception:
                        photo_path = ""

            database.save_profile(
                user_id=user.id,
                first_name=getattr(user, "first_name", "") or "",
                username=getattr(user, "username", "") or "",
                bio=bio,
                photo_path=photo_path,
            )
            database.link_user_group(user.id, group_name)

            username = getattr(user, "username", "") or ""
            queued_username = False
            queued_snoop = False
            if username:
                queued_username = database.queue_username_check_if_needed(user.id, username)
                if queued_username:
                    self._emit(
                        event_callback,
                        "username_pending",
                        user_id=user.id,
                        username=username,
                    )
                queued_snoop = database.queue_enrichment_check_if_needed(user.id, username, "snoop")
                if queued_snoop:
                    self._emit(event_callback, "enrichment_pending",
                               user_id=user.id, username=username, tool_name="snoop")
                if database.queue_enrichment_check_if_needed(user.id, username, "maigret"):
                    self._emit(event_callback, "enrichment_pending",
                               user_id=user.id, username=username, tool_name="maigret")
            else:
                database.mark_username_skipped(user.id, "")
                database.mark_enrichment_skipped(user.id, "", "snoop")
                database.mark_enrichment_skipped(user.id, "", "maigret")

            result = {
                "user_id": user.id,
                "username": username,
                "first_name": getattr(user, "first_name", "") or "",
                "queued_username": queued_username,
                "queued_snoop": queued_snoop,
                "stats": database.get_dashboard_stats(),
            }
            self._emit(event_callback, "profile_collected", **result)
            self._emit(event_callback, "progress", stats=result["stats"])
            return result
        except Exception as exc:
            self._emit(event_callback, "error", message=f"Failed to process profile {target}: {exc}")
            raise
        finally:
            await client.disconnect()

    async def collect_group(
        self,
        group_name: str,
        limit_new_users: int,
        event_callback: EventCallback = None,
    ) -> CollectionStats:
        database.init_db()
        if IMPORT_ERROR is not None:
            raise RuntimeError(
                "Telethon is not installed. Install dependencies from requirements.txt first."
            )
        if not self.api_id or not self.api_hash:
            raise RuntimeError(
                "Telegram API credentials are required. Set TELEGRAM_API_ID and TELEGRAM_API_HASH "
                "(or TG_API_ID and TG_API_HASH), or enter them in the desktop app."
            )
        if not self.api_id.isdigit():
            raise RuntimeError("Telegram API ID must be a number.")

        stats = CollectionStats()
        existing_users = database.get_existing_user_ids()

        client = TelegramClient(self.session_name, int(self.api_id), self.api_hash)
        await client.start()
        self._emit(event_callback, "log", message=f"Collecting users from @{group_name}")

        try:
            async for user in client.iter_participants(group_name):
                is_existing = user.id in existing_users

                if is_existing:
                    stats.existing_profiles += 1
                    database.save_profile(
                        user_id=user.id,
                        first_name=user.first_name,
                        username=user.username,
                        bio="",
                        photo_path="",
                    )
                    database.link_user_group(user.id, group_name)
                    if user.username and database.queue_username_check_if_needed(user.id, user.username):
                        stats.queued_usernames += 1
                        self._emit(
                            event_callback,
                            "username_pending",
                            user_id=user.id,
                            username=user.username,
                        )
                    if user.username and database.queue_enrichment_check_if_needed(user.id, user.username, "snoop"):
                        self._emit(event_callback, "enrichment_pending",
                                   user_id=user.id, username=user.username, tool_name="snoop")
                    if user.username and database.queue_enrichment_check_if_needed(user.id, user.username, "maigret"):
                        self._emit(event_callback, "enrichment_pending",
                                   user_id=user.id, username=user.username, tool_name="maigret")
                    self._emit(
                        event_callback,
                        "progress",
                        stats=database.get_dashboard_stats(),
                    )
                    continue

                bio = ""
                try:
                    full_user = await client(GetFullUserRequest(id=user))
                    bio = full_user.full_user.about or ""
                except FloodWaitError as exc:
                    self._emit(
                        event_callback,
                        "log",
                        message=f"Telegram rate limit reached. Sleeping {exc.seconds}s.",
                    )
                    await asyncio.sleep(exc.seconds)
                    continue
                except Exception:
                    bio = ""

                photo_path = ""
                if user.photo:
                    photo_file = database.AVATARS_DIR / f"{user.id}.jpg"
                    photo_path = str(Path("avatars") / f"{user.id}.jpg").replace("\\", "/")
                    if not photo_file.exists():
                        try:
                            await client.download_profile_photo(user, file=str(photo_file))
                        except FloodWaitError as exc:
                            self._emit(
                                event_callback,
                                "log",
                                message=f"Photo download rate limit reached. Sleeping {exc.seconds}s.",
                            )
                            await asyncio.sleep(exc.seconds)
                        except Exception:
                            photo_path = ""

                database.save_profile(
                    user_id=user.id,
                    first_name=user.first_name,
                    username=user.username,
                    bio=bio,
                    photo_path=photo_path,
                )
                database.link_user_group(user.id, group_name)
                existing_users.add(user.id)
                stats.new_profiles += 1

                if user.username:
                    if database.queue_username_check_if_needed(user.id, user.username):
                        stats.queued_usernames += 1
                        self._emit(
                            event_callback,
                            "username_pending",
                            user_id=user.id,
                            username=user.username,
                        )
                    if database.queue_enrichment_check_if_needed(user.id, user.username, "snoop"):
                        self._emit(event_callback, "enrichment_pending",
                                   user_id=user.id, username=user.username, tool_name="snoop")
                    if database.queue_enrichment_check_if_needed(user.id, user.username, "maigret"):
                        self._emit(event_callback, "enrichment_pending",
                                   user_id=user.id, username=user.username, tool_name="maigret")
                else:
                    database.mark_username_skipped(user.id, "")
                    database.mark_enrichment_skipped(user.id, "", "snoop")
                    database.mark_enrichment_skipped(user.id, "", "maigret")
                    stats.skipped_usernames += 1

                self._emit(
                    event_callback,
                    "log",
                    message=f"Saved profile {user.id} ({user.first_name or 'NoName'})",
                )
                self._emit(
                    event_callback,
                    "progress",
                    stats=database.get_dashboard_stats(),
                )

                if stats.new_profiles >= limit_new_users:
                    self._emit(
                        event_callback,
                        "log",
                        message=f"Reached limit of {limit_new_users} new profiles for @{group_name}",
                    )
                    break

                await asyncio.sleep(self.delay_seconds)
        except Exception as exc:
            self._emit(event_callback, "error", message=f"Failed to process @{group_name}: {exc}")
            raise
        finally:
            await client.disconnect()

        self._emit(event_callback, "completed", stats=stats.__dict__)
        self._emit(event_callback, "progress", stats=database.get_dashboard_stats())
        return stats
