from console_utils import configure_console_output
import database

def main() -> int:
    configure_console_output()
    rows = database.list_user_connections()
    print(
        f"User to chat links (records found: {len(rows)})\n" + "=" * 50
    )

    for row in rows:
        username = f"@{row['username']}" if row["username"] else "[hidden]"
        print(f"{row['first_name']} ({username})")
        print(f"Chat: @{row['group_name']}")
        print(f"Collected at: {row['parsed_at']}")
        print("-" * 50)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
