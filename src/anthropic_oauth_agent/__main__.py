"""Command line entry point: `anthropic-oauth-agent [--dry-run] [--list] ...`."""

import argparse
import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config, uia
from .agent import Agent
from .policy import classify

REPO_ROOT = Path(__file__).resolve().parents[2]
MUTEX_NAME = "Local\\anthropic_oauth_agent"
ERROR_ALREADY_EXISTS = 183


def _setup_logging(verbose: bool) -> None:
    log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_dir / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
    ]
    if sys.stderr is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    logging.getLogger("comtypes").setLevel(logging.WARNING)


def _single_instance() -> object | None:
    """Hold a named mutex for the process lifetime; None if another agent already runs."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def _list_pages() -> None:
    """Print every browser window and the web pages in it, with the step each would be."""
    for window in uia.browser_windows():
        print(f"[{window.process}] {window.title}")
        uia.wake_accessibility(window.hwnd)
        for page in uia.web_pages(window.control):
            step = classify(page.url)
            label = step.value if step else "-"
            print(f"    {label:18} {page.url[:140]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anthropic-oauth-agent", description=__doc__)
    parser.add_argument("--email", default=config.TARGET_EMAIL, help="Google account to pick")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between scans")
    parser.add_argument("--dry-run", action="store_true", help="log what would be clicked, click nothing")
    parser.add_argument("--once", action="store_true", help="scan once and exit")
    parser.add_argument("--list", action="store_true", help="print browser windows and page URLs, then exit")
    parser.add_argument("--all-windows", action="store_true",
                        help="inspect every browser window, not only ones whose title looks like a login")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        _list_pages()
        return 0

    if not args.email:
        parser.error(f"no Google account set: copy local.example.toml to {config.LOCAL_CONFIG.name} "
                     "and set email, or pass --email")

    _setup_logging(args.verbose)
    agent =Agent(email=args.email, dry_run=args.dry_run, title_filter=not args.all_windows)
    if args.once:
        agent.tick()
        return 0

    mutex = _single_instance()
    if mutex is None:
        logging.getLogger("anthropic_oauth_agent").error("another agent is already running; exiting")
        return 1
    try:
        agent.run(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
