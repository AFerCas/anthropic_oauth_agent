"""Pure URL logic: which step of the Claude Code login a page is, and whether it is safe to act on.

Nothing here touches the UI, so every gate is unit-testable.
"""

from enum import Enum
from urllib.parse import parse_qs, urljoin, urlsplit

from . import config


class Step(Enum):
    CLAUDE_LOGIN = "claude-login"          # claude.ai login form in front of a Claude Code authorize
    CLAUDE_AUTHORIZE = "claude-authorize"  # "Claude Code wants to connect" consent
    GOOGLE_CHOOSER = "google-chooser"      # Google account picker for claude.ai
    GOOGLE_CONSENT = "google-consent"      # Google "continue to Claude" confirmation
    GOOGLE_SIGNED_OUT = "google-signed-out"  # Google wants an email/password: needs a human

    @property
    def is_google(self) -> bool:
        return self.value.startswith("google-")


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_https(url: str) -> bool:
    return url.lower().startswith("https://")


def _params(url: str) -> dict[str, list[str]]:
    try:
        return parse_qs(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return {}


def _first(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key)
    return values[0] if values else ""


def is_allowed_redirect(redirect_uri: str) -> bool:
    if redirect_uri in config.ALLOWED_REDIRECT_URIS:
        return True
    parts = urlsplit(redirect_uri)
    return (
        parts.scheme == "http"
        and (parts.hostname or "").lower() in config.LOCAL_REDIRECT_HOSTS
        and parts.path == "/callback"
    )


def is_claude_code_authorize(url: str) -> bool:
    """True for an Anthropic /oauth/authorize URL issued by Claude Code itself."""
    if not _is_https(url) or _host(url) not in config.ANTHROPIC_HOSTS:
        return False
    if not urlsplit(url).path.rstrip("/").endswith("/oauth/authorize"):
        return False
    q = _params(url)
    return (
        _first(q, "client_id") in config.CLAUDE_CODE_CLIENT_IDS
        and _first(q, "response_type") == "code"
        and is_allowed_redirect(_first(q, "redirect_uri"))
    )


def _login_return_target(url: str) -> str:
    q = _params(url)
    for key in ("returnTo", "return_to", "returnUrl", "redirect", "next"):
        target = _first(q, key)
        if target:
            # returnTo is usually a site-relative path; resolve it against the login page.
            return urljoin(url, target)
    return ""


def is_claude_code_login(url: str) -> bool:
    """True for the Anthropic login form when it leads to a Claude Code authorize."""
    if not _is_https(url) or _host(url) not in config.ANTHROPIC_HOSTS:
        return False
    if urlsplit(url).path.rstrip("/") not in config.ANTHROPIC_LOGIN_PATHS:
        return False
    return is_claude_code_authorize(_login_return_target(url))


def _nested_params(url: str, depth: int = 3) -> list[dict[str, list[str]]]:
    """Query params of url plus of any URL-valued params inside it (continue=..., etc.)."""
    found = [_params(url)]
    if depth <= 0:
        return found
    for values in found[0].values():
        for value in values:
            if value.startswith(("http://", "https://")):
                found.extend(_nested_params(value, depth - 1))
    return found


def is_google_for_claude(url: str) -> bool:
    """True for a Google accounts page that is part of claude.ai's "Continue with Google"."""
    if not _is_https(url) or _host(url) not in config.GOOGLE_HOSTS:
        return False
    for q in _nested_params(url):
        if _first(q, "client_id") in config.CLAUDE_GOOGLE_CLIENT_IDS:
            return True
        for key in ("origin", "app_domain"):
            if _first(q, key).rstrip("/") in config.CLAUDE_ORIGINS:
                return True
        redirect = _first(q, "redirect_uri")
        if redirect and _is_https(redirect) and _host(redirect) in config.ANTHROPIC_HOSTS:
            return True
    return False


def classify(url: str) -> Step | None:
    """Map a page URL to a login step, or None if the agent must leave it alone."""
    if is_claude_code_authorize(url):
        return Step.CLAUDE_AUTHORIZE
    if is_claude_code_login(url):
        return Step.CLAUDE_LOGIN
    if not is_google_for_claude(url):
        return None
    path = urlsplit(url).path.lower()
    if "chooser" in path or "chooseaccount" in path:
        return Step.GOOGLE_CHOOSER
    if any(part in path for part in ("identifier", "challenge", "pwd", "password")):
        return Step.GOOGLE_SIGNED_OUT
    if path.startswith("/signin/oauth") or "consent" in path:
        return Step.GOOGLE_CONSENT
    return None
