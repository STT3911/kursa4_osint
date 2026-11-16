"""Explicit local review CLI. Run from any working directory."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_identity_review import process_qwen_review
from spiderfoot_integration import process_spiderfoot_check


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--username", help="Required with --spiderfoot")
    parser.add_argument("--spiderfoot", action="store_true")
    parser.add_argument("--qwen", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if not args.spiderfoot and not args.qwen:
        parser.error("Choose --spiderfoot and/or --qwen")
    if args.spiderfoot and not args.username:
        parser.error("--spiderfoot requires --username")
    status = 0
    if args.spiderfoot:
        result = process_spiderfoot_check(args.user_id, args.username)
        print(json.dumps(result, ensure_ascii=False))
        status |= int(result["status"] != "done")
    if args.qwen:
        if not 1 <= args.limit <= 500:
            parser.error("--limit must be between 1 and 500")
        result = process_qwen_review(args.user_id, args.limit)
        print(json.dumps(result, ensure_ascii=False))
        status |= int(result["status"] != "done")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
