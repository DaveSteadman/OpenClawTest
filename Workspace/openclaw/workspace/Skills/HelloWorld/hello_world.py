#!/usr/bin/env python3
import argparse
import datetime as dt
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone hello world cron test")
    parser.add_argument(
        "--log",
        default="c:/Users/daves/.openclaw/logs/hello_world_cron.log",
        help="Log file path",
    )
    args = parser.parse_args()

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    payload = {"status": "ok", "message": "Hello from standalone cron", "ts": now}

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())