"""Static configuration: who to log in as, and which pages the agent may touch."""

import re
import tomllib
from pathlib import Path

# Personal settings live in local.toml at the repo root, which is gitignored.
# Copy local.example.toml to local.toml and fill it in.
LOCAL_CONFIG = Path(__file__).resolve().parents[2] / "local.toml"


def _local_settings() -> dict:
    try:
        with LOCAL_CONFIG.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


# Google account to log in as; None until local.toml sets it (or --email is passed).
TARGET_EMAIL: str | None = _local_settings().get("email")

# Claude Code's OAuth client id, taken from the installed Claude Code binary
# (constant CLIENT_ID next to CLAUDE_AI_AUTHORIZE_URL / CONSOLE_AUTHORIZE_URL).
CLAUDE_CODE_CLIENT_IDS = frozenset({"9d1c250a-e61b-44d9-88ed-5944d1962f5e"})

# Hosts that serve the Anthropic login / authorize pages.
ANTHROPIC_HOSTS = frozenset({
    "claude.ai",
    "claude.com",
    "platform.claude.com",
    "console.anthropic.com",
})

# Paths on ANTHROPIC_HOSTS that show the login form in front of /oauth/authorize.
ANTHROPIC_LOGIN_PATHS = frozenset({"/login", "/signin", "/sign-in", "/cai/login"})

# Where Claude Code lets the authorization code go. Anything else is not Claude Code.
ALLOWED_REDIRECT_URIS = frozenset({
    "https://platform.claude.com/oauth/code/callback",
    "https://console.anthropic.com/oauth/code/callback",
})
LOCAL_REDIRECT_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})

GOOGLE_HOSTS = frozenset({"accounts.google.com"})

# A Google sign-in page counts as "for Claude" if one of these shows up in its
# query string (top level or nested in continue=/redirect params).
CLAUDE_ORIGINS = frozenset({
    "https://claude.ai",
    "https://claude.com",
    "https://platform.claude.com",
    "https://console.anthropic.com",
})
# Google OAuth client that claude.ai uses for "Continue with Google" (observed 2026-09-25).
CLAUDE_GOOGLE_CLIENT_IDS = frozenset({
    "1062961139910-l2m55cb9h51u5cuc9c56eb3fevouidh9.apps.googleusercontent.com",
})

# Top-level browser processes to watch. Electron apps (VS Code, Slack, ...) share
# Chromium's window class, so the process name is what tells a browser apart.
BROWSER_PROCESSES = frozenset({
    "chrome.exe", "msedge.exe", "vivaldi.exe", "brave.exe", "opera.exe",
    "chromium.exe", "arc.exe", "thorium.exe", "browser.exe",
    "firefox.exe", "librewolf.exe", "waterfox.exe", "floorp.exe", "zen.exe",
})

# Only windows whose title matches are inspected deeply; keeps the idle loop cheap.
TITLE_HINT = re.compile(r"claude|anthropic|google|sign.?in|log.?in|anmeld|authori[sz]", re.I)

# Button labels (compared case-insensitively, exact match) per step.
AUTHORIZE_LABELS = frozenset({
    "authorize", "autorisieren", "allow", "zulassen", "erlauben",
    "approve", "genehmigen", "accept", "akzeptieren", "grant access", "zugriff gewähren",
})
# Shown on the authorize page when claude.ai is logged in as someone other than TARGET_EMAIL.
SWITCH_ACCOUNT_LABELS = frozenset({
    "switch account", "konto wechseln", "account wechseln",
    "use a different account", "anderes konto verwenden",
})
GOOGLE_CONTINUE_LABELS = frozenset({
    "continue", "weiter", "allow", "zulassen", "erlauben", "fortfahren",
    "confirm", "bestätigen",
})
# "Continue with Google" on the Claude login page: any button mentioning Google.
GOOGLE_BUTTON_PATTERN = re.compile(r"\bgoogle\b", re.I)

# How long after seeing a Claude Code login/authorize page Google pages may be clicked.
ARM_SECONDS = 300
# Minimum gap before clicking the same step on the same URL again, and a cap.
RETRY_SECONDS = 8.0
MAX_CLICKS_PER_PAGE = 3
