from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from config import env_first, load_env_file

_PID_FILE = Path(__file__).parent / ".bot.pid"

def _kill_previous_bot() -> None:
    if not _PID_FILE.exists():
        return
    try:
        old_pid = int(_PID_FILE.read_text().strip())
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(old_pid)],
                capture_output=True,
            )
        else:
            os.kill(old_pid, 15)
    except Exception:
        pass
    finally:
        _PID_FILE.unlink(missing_ok=True)

def _start_bot() -> subprocess.Popen | None:
    load_env_file()
    token = env_first("OSINT_BOT_TOKEN")
    if not token:
        print("[run] OSINT_BOT_TOKEN не задан — бот не запущен")
        print("[run] Добавь в .env:  OSINT_BOT_TOKEN=<твой_токен>")
        return None

    _kill_previous_bot()

    kwargs: dict = dict(
        args=[sys.executable, str(Path(__file__).parent / "osint_bot.py")],
    )

    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

    proc = subprocess.Popen(**kwargs)
    _PID_FILE.write_text(str(proc.pid))
    print(f"[run] Telegram-бот запущен  (pid={proc.pid})")
    return proc

def main() -> None:
    bot_proc = _start_bot()

    try:
        import app as desktop_app
        desktop_app.main()
    except KeyboardInterrupt:
        pass
    finally:
        if bot_proc and bot_proc.poll() is None:
            bot_proc.terminate()
            try:
                bot_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                bot_proc.kill()
            print("[run] Telegram-бот остановлен")
        _PID_FILE.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
