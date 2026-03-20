from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

from .bot import GroupChatBot
from .config import load_config
from .logging_utils import log_event
from .service import HouseHunterService


def main(argv: Iterable[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Watch Zurich housing sites and notify Telegram.")
    parser.add_argument("--config", required=True, help="Path to the JSON config file.")
    parser.add_argument("--dry-run", action="store_true", help="Print messages instead of sending them.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="Run a single sweep.")
    loop_parser = subparsers.add_parser("loop", help="Run continuously.")
    loop_parser.add_argument("--interval-seconds", type=int, default=900, help="Delay between sweeps.")
    bot_loop_parser = subparsers.add_parser("bot-loop", help="Run Telegram command polling and scheduled sweeps.")
    bot_loop_parser.add_argument("--interval-seconds", type=int, default=900, help="Delay between sweeps.")
    bot_loop_parser.add_argument("--poll-timeout-seconds", type=int, default=20, help="Telegram long-poll timeout.")

    args = parser.parse_args(list(argv) if argv is not None else None)
    config = load_config(args.config)
    log_event("cli", "loaded config from {0}".format(args.config))

    if args.command == "run":
        return _run_once(config, dry_run=args.dry_run)

    if args.command == "loop":
        return _run_loop(config, dry_run=args.dry_run, interval_seconds=args.interval_seconds)

    if args.command == "bot-loop":
        return _run_bot_loop(
            config,
            dry_run=args.dry_run,
            interval_seconds=args.interval_seconds,
            poll_timeout_seconds=args.poll_timeout_seconds,
        )

    parser.error("Unknown command")
    return 2


def _run_once(config, dry_run: bool) -> int:
    started_at = time.time()
    log_event("cli", "starting single run (dry_run={0})".format("yes" if dry_run else "no"))
    service = HouseHunterService(config, dry_run_override=dry_run)
    try:
        stats = service.run_once()
    finally:
        service.close()
    _print_stats(stats)
    log_event("cli", "single run finished in {0:.1f}s".format(time.time() - started_at))
    return 0 if all(not item.errors for item in stats) else 1


def _run_loop(config, dry_run: bool, interval_seconds: int) -> int:
    while True:
        exit_code = _run_once(config, dry_run=dry_run)
        if exit_code != 0:
            return exit_code
        log_event("cli", "sleeping {0}s before next run".format(interval_seconds))
        time.sleep(interval_seconds)


def _run_bot_loop(config, dry_run: bool, interval_seconds: int, poll_timeout_seconds: int) -> int:
    log_event(
        "cli",
        "starting bot loop (dry_run={0}, scrape_interval={1}s, poll_timeout={2}s)".format(
            "yes" if dry_run else "no",
            interval_seconds,
            poll_timeout_seconds,
        ),
    )
    bot = GroupChatBot(config, dry_run=dry_run)
    try:
        bot.serve(scrape_interval_seconds=interval_seconds, poll_timeout_seconds=poll_timeout_seconds)
    finally:
        bot.close()
    return 0


def _print_stats(stats) -> None:
    for item in stats:
        print(
            "[{name}] fetched={fetched} matched={matched} bootstrap={bootstrap} notified={notified} "
            "seen={seen} filtered={filtered}".format(
                name=item.source_name,
                fetched=item.fetched,
                matched=item.matched,
                bootstrap=item.new_seen_on_bootstrap,
                notified=item.notified,
                seen=item.skipped_seen,
                filtered=item.skipped_filtered,
            )
        )
        for error in item.errors:
            print("  error: {0}".format(error))


if __name__ == "__main__":
    sys.exit(main())
