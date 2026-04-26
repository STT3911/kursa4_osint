from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import database

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
        self.api_id = str(api_id or "").strip()
        self.api_hash = str(api_hash or "").strip()
        self.session_name = session_name or "osint_session"
        self.delay_seconds = delay_seconds

    def _emit(self, callback: EventCallback, event_type: str, **payload: object) -> None:
        if callback is not None:
            callback({"type": event_type, **payload})

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
                "or enter them in the desktop app."
            )

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
                else:
                    database.mark_username_skipped(user.id, "")
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
