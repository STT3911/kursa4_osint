from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
_ENV_LOADED = False

def load_env_file(path: Path | None = None, override: bool = False) -> None:
    global _ENV_LOADED
    env_path = path or ENV_PATH
    if _ENV_LOADED and path is None:
        return
    _ENV_LOADED = True
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = value

def env_first(*names: str) -> str:
    load_env_file()
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""
