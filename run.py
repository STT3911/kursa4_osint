"""
Единая точка входа — запускает desktop-приложение и Telegram-бот вместе.

Использование:
    .venv\\Scripts\\python.exe run.py

Telegram-бот стартует автоматически если в .env задан OSINT_BOT_TOKEN.
При закрытии десктопного приложения бот тоже останавливается.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from config import env_first, load_env_file


def _start_bot() -> subprocess.Popen | None:
    load_env_file()
    token = env_first("OSINT_BOT_TOKEN")
    if not token:
        print("[run] OSINT_BOT_TOKEN не задан — бот не запущен")
        print("[run] Добавь в .env:  OSINT_BOT_TOKEN=<твой_токен>")
        return None

    kwargs: dict = dict(
        args=[sys.executable, str(Path(__file__).parent / "osint_bot.py")],
    )

    # На Windows открываем отдельное консольное окно для логов бота
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

    proc = subprocess.Popen(**kwargs)
    print(f"[run] Telegram-бот запущен  (pid={proc.pid})")
    return proc


def main() -> None:
    bot_proc = _start_bot()

    try:
        import app as desktop_app
        desktop_app.main()
    finally:
        if bot_proc and bot_proc.poll() is None:
            bot_proc.terminate()
            try:
                bot_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                bot_proc.kill()
            print("[run] Telegram-бот остановлен")


if __name__ == "__main__":
    main()
