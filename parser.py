import argparse
import asyncio
import os
import sys

from console_utils import configure_console_output
import database
from telegram_service import TelegramCollector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Telegram profiles and queue Sherlock enrichment."
    )
    parser.add_argument(
        "--group",
        default="rabota_chaty1",
        help="Telegram group username without @.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=400,
        help="Maximum number of new profiles to collect.",
    )
    parser.add_argument(
        "--api-id",
        default=os.getenv("TELEGRAM_API_ID", ""),
        help="Telegram API ID. Falls back to TELEGRAM_API_ID.",
    )
    parser.add_argument(
        "--api-hash",
        default=os.getenv("TELEGRAM_API_HASH", ""),
        help="Telegram API hash. Falls back to TELEGRAM_API_HASH.",
    )
    parser.add_argument(
        "--session",
        default=os.getenv("TELEGRAM_SESSION", "osint_session"),
        help="Telethon session name.",
    )
    return parser


def main() -> int:
    configure_console_output()
    args = build_parser().parse_args()
    database.init_db()

    collector = TelegramCollector(
        api_id=args.api_id,
        api_hash=args.api_hash,
        session_name=args.session,
    )

    def emit(event: dict) -> None:
        event_type = event.get("type")
        if event_type == "log":
            print(event.get("message", ""))
        elif event_type == "progress":
            print(
                "profiles={profiles} queued={queued_checks} checks_done={completed_checks} "
                "social_accounts={social_accounts}".format(**event["stats"])
            )
        elif event_type == "completed":
            stats = event["stats"]
            print(
                "Collection finished: new={new_profiles} existing={existing_profiles} "
                "queued={queued_usernames} skipped={skipped_usernames}".format(**stats)
            )
        elif event_type == "error":
            print(event.get("message", "Unknown error"), file=sys.stderr)

    try:
        asyncio.run(
            collector.collect_group(
                group_name=args.group,
                limit_new_users=args.limit,
                event_callback=emit,
            )
        )
    except Exception as exc:
        print(f"Parser failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
