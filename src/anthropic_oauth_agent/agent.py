"""The polling loop: find Claude Code login pages in any browser and click through them."""

import logging
import time
from dataclasses import dataclass, field

from . import config, uia
from .policy import Step, classify

log = logging.getLogger("anthropic_oauth_agent")


@dataclass
class _Attempts:
    count: int = 0
    last: float = 0.0


@dataclass
class Agent:
    email: str
    dry_run: bool = False
    title_filter: bool = True
    armed_until: float = 0.0
    _attempts: dict[tuple[Step, str], _Attempts] = field(default_factory=dict)
    _noted: set[tuple[str, str]] = field(default_factory=set)

    def run(self, interval: float) -> None:
        log.info(
            "watching browsers for Claude Code login as %s%s",
            self.email, " (dry run: nothing will be clicked)" if self.dry_run else "",
        )
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("scan failed; continuing")
            time.sleep(interval)

    def tick(self) -> None:
        for window in uia.browser_windows():
            if self.title_filter and not config.TITLE_HINT.search(window.title):
                continue
            uia.wake_accessibility(window.hwnd)
            for page in uia.web_pages(window.control):
                step = classify(page.url)
                if step is not None:
                    self.handle(step, page, window)

    @property
    def armed(self) -> bool:
        return time.monotonic() < self.armed_until

    def _arm(self) -> None:
        if not self.armed:
            log.info("Claude Code login detected; Google steps enabled for %ss", config.ARM_SECONDS)
        self.armed_until = time.monotonic() + config.ARM_SECONDS

    def _note_once(self, key: str, url: str, message: str, *args) -> None:
        if (key, url) not in self._noted:
            self._noted.add((key, url))
            log.warning(message, *args)

    def _may_click(self, step: Step, url: str) -> bool:
        attempts = self._attempts.get((step, url))
        if attempts is None:
            return True
        if attempts.count >= config.MAX_CLICKS_PER_PAGE:
            self._note_once("gave-up", url, "%s: clicked %s times without the page moving on; leaving it",
                            step.value, attempts.count)
            return False
        return time.monotonic() - attempts.last >= config.RETRY_SECONDS

    def handle(self, step: Step, page: uia.WebPage, window: uia.BrowserWindow) -> None:
        if step in (Step.CLAUDE_LOGIN, Step.CLAUDE_AUTHORIZE):
            self._arm()
        elif not self.armed:
            self._note_once("unarmed", page.url,
                            "%s in %s ignored: no Claude Code login seen in the last %ss",
                            step.value, window.process, config.ARM_SECONDS)
            return

        if step is Step.GOOGLE_SIGNED_OUT:
            self._note_once("signed-out", page.url,
                            "Google asks for an email/password in %s; %s is not signed in to Google "
                            "in this browser. Sign in once by hand, then the agent can take over.",
                            window.process, self.email)
            return
        if not self._may_click(step, page.url):
            return

        target, what = self._target(step, page)
        if target is None:
            self._note_once("no-target", page.url, "%s: no %s found yet; clickable elements: %s",
                            step.value, what, uia.clickable_names(page.document))
            return

        name = uia.safe_name(target)
        attempts = self._attempts.setdefault((step, page.url), _Attempts())
        if not uia.is_enabled(target):
            # Only the authorize page needs focus to enable its button. Elsewhere a
            # disabled button means the page is busy (e.g. the Google popup is open),
            # and pulling that window forward would hide the popup.
            if step is not Step.CLAUDE_AUTHORIZE:
                return
            if self.dry_run:
                log.info("[dry run] %s in %s: %r is disabled; would bring the window to the front",
                         step.value, window.process, name)
                return
            attempts.last = time.monotonic()  # throttles focus changes to one per RETRY_SECONDS
            if not uia.wait_until_enabled(target, window):
                log.warning("%s in %s: %r stays disabled even with the window in front; will retry",
                            step.value, window.process, name)
                return
        attempts.count += 1
        attempts.last = time.monotonic()
        if self.dry_run:
            log.info("[dry run] %s in %s: would click %r", step.value, window.process, name)
            return
        method = uia.click(target)
        log.info("%s in %s: clicked %r (%s)", step.value, window.process, name, method)
        if step is Step.CLAUDE_AUTHORIZE and name.casefold() in config.AUTHORIZE_LABELS:
            log.info("Claude Code authorized as %s", self.email)

    def _target(self, step: Step, page: uia.WebPage):
        doc = page.document
        if step is Step.CLAUDE_AUTHORIZE:
            # The page says "Logged in as <email>"; never authorize a different account.
            emails = uia.page_emails(doc)
            if self.email.casefold() in emails:
                return uia.find_button(doc, config.AUTHORIZE_LABELS), "authorize button"
            if emails:
                return (uia.find_button(doc, config.SWITCH_ACCOUNT_LABELS),
                        f"switch-account button (logged in as {', '.join(sorted(emails))})")
            return None, f"'Logged in as {self.email}' text"
        if step is Step.CLAUDE_LOGIN:
            # An existing-session account picker beats starting a fresh Google login.
            entry = uia.find_account_entry(doc, self.email)
            if entry is not None:
                return entry, "account entry"
            return uia.find_button_matching(doc, config.GOOGLE_BUTTON_PATTERN), "Continue with Google button"
        if step is Step.GOOGLE_CHOOSER:
            return uia.find_account_entry(doc, self.email), f"account entry for {self.email}"
        if step is Step.GOOGLE_CONSENT:
            return uia.find_button(doc, config.GOOGLE_CONTINUE_LABELS), "continue button"
        return None, "target"
