"""Drives a real Chrome against a local fixture page. Opt in with ANTHROPIC_OAUTH_AGENT_LIVE=1."""

import os
import subprocess
import time
from pathlib import Path

import pytest
import uiautomation as auto

from anthropic_oauth_agent import uia

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
FIXTURE = Path(__file__).parent / "fixtures" / "account_chooser.html"

pytestmark = pytest.mark.skipif(
    os.environ.get("ANTHROPIC_OAUTH_AGENT_LIVE") != "1" or not CHROME.exists(),
    reason="live UI test; set ANTHROPIC_OAUTH_AGENT_LIVE=1 (needs Chrome)",
)


def _wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.5)
    return None


def _fixture_window():
    for window in uia.browser_windows():
        if window.title.startswith("fixture chooser") or window.title.startswith("clicked"):
            return window
    return None


@pytest.fixture
def chrome(tmp_path):
    proc = subprocess.Popen([
        str(CHROME), f"--user-data-dir={tmp_path}", "--no-first-run", "--new-window", FIXTURE.as_uri(),
    ])
    window = _wait_for(_fixture_window)
    assert window, "fixture window did not open"
    window.control.SetActive()
    yield window
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


def _fixture_page(window):
    # web_pages() keeps only http(s) documents; the fixture is file://, so look it up directly.
    uia.wake_accessibility(window.hwnd)
    documents = uia._find_all(window.control, uia._type_condition(auto.ControlType.DocumentControl))
    for doc in documents:
        url = uia.document_url(doc)
        if url.startswith("file:"):
            return uia.WebPage(url, doc)
    return None


def test_finds_and_clicks_account_row(chrome):
    page = _wait_for(lambda: _fixture_page(chrome))
    assert page, "fixture document not exposed through UI Automation"

    assert "target@example.com" in uia.page_emails(page.document)
    entry = _wait_for(lambda: uia.find_account_entry(page.document, "target@example.com"))
    assert entry is not None
    assert "target@example.com" in uia.safe_name(entry)

    uia.click(entry)
    assert _wait_for(lambda: _fixture_window() and _fixture_window().title.startswith("clicked target"))


def test_missing_account_is_not_guessed(chrome):
    page = _wait_for(lambda: _fixture_page(chrome))
    assert page
    assert uia.find_account_entry(page.document, "nobody@example.com") is None
