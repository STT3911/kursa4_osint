"""Smoke test with synthetic profiles only; does not read or write the profile database."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qwen_identity import QwenResponseError, get_reviewer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug-raw", action="store_true",
                        help="Print raw model output if validation fails (synthetic data only).")
    args = parser.parse_args()
    profile = {"username": "alex_example", "first_name": "Alex Example",
               "bio": "Maintainer of CedarMap. Python developer."}
    account = {"observed_username": "alex-example", "display_name": "Alex Example",
               "bio": "Maintainer of CedarMap. Python developer."}
    print("Loading local Qwen, building JSON constraint, and comparing...", flush=True)
    started = time.perf_counter()
    try:
        result = get_reviewer().review(profile, account)
    except QwenResponseError as exc:
        print(f"Validation failed: {exc}", flush=True)
        if args.debug_raw:
            print("Raw synthetic model response:\n" + exc.raw_response, flush=True)
        return 1
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Seconds:", round(time.perf_counter() - started, 1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
