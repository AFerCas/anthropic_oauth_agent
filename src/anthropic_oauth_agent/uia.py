"""Windows UI Automation access to browser windows, page URLs and page controls.

Chromium only builds its accessibility tree once a client asks for it, so every
inspected window is first "woken" with WM_GETOBJECT. This works on running
browsers without restart flags (verified on Chrome 153 and Vivaldi 8.2).
"""

import ctypes
import os
import re
import time
from ctypes import wintypes
from dataclasses import dataclass

import uiautomation as auto
from uiautomation import uiautomation as _ua

from . import config

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumChildWindows.argtypes = [wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM]
_user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
]

WM_GETOBJECT = 0x003D
OBJID_CLIENT = -4
UIA_ROOT_OBJECT_ID = -25
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TREE_SCOPE_DESCENDANTS = 4

BROWSER_WINDOW_CLASSES = ("Chrome_WidgetWin_1", "MozillaWindowClass")

CLICKABLE_TYPES = (
    auto.ControlType.ButtonControl,
    auto.ControlType.HyperlinkControl,
    auto.ControlType.ListItemControl,
    auto.ControlType.MenuItemControl,
    auto.ControlType.RadioButtonControl,
)


@dataclass
class BrowserWindow:
    hwnd: int
    title: str
    process: str

    @property
    def control(self) -> auto.Control:
        return auto.ControlFromHandle(self.hwnd)


@dataclass
class WebPage:
    url: str
    document: auto.Control


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(handle)


def browser_windows() -> list[BrowserWindow]:
    """Visible top-level windows that belong to a known browser process."""
    found: list[BrowserWindow] = []

    def visit(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and _class_name(hwnd) in BROWSER_WINDOW_CLASSES:
            process = _process_name(hwnd)
            if process in config.BROWSER_PROCESSES:
                found.append(BrowserWindow(hwnd, _window_title(hwnd), process))
        return True

    _user32.EnumWindows(_WNDENUMPROC(visit), 0)
    return found


def wake_accessibility(hwnd: int) -> None:
    """Ask the window and its render widgets for their accessibility root.

    Chromium turns on its web-content accessibility tree when it receives this.
    """
    targets = [hwnd]

    def visit(child, _):
        if _class_name(child) == "Chrome_RenderWidgetHostHWND":
            targets.append(child)
        return True

    _user32.EnumChildWindows(hwnd, _WNDENUMPROC(visit), 0)
    result = ctypes.c_size_t()
    for target in targets:
        for object_id in (OBJID_CLIENT, UIA_ROOT_OBJECT_ID):
            _user32.SendMessageTimeoutW(
                target, WM_GETOBJECT, 0, object_id, SMTO_ABORTIFHUNG, 500, ctypes.byref(result)
            )


def _iuia():
    return _ua._AutomationClient.instance().IUIAutomation


def _find_all(root: auto.Control, condition) -> list[auto.Control]:
    try:
        array = root.Element.FindAll(TREE_SCOPE_DESCENDANTS, condition)
    except Exception:
        return []
    if not array:
        return []
    controls = []
    for i in range(array.Length):
        control = auto.Control.CreateControlFromElement(array.GetElement(i))
        if control is not None:
            controls.append(control)
    return controls


def _type_condition(*control_types: int):
    iuia = _iuia()
    conditions = [
        iuia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, t) for t in control_types
    ]
    condition = conditions[0]
    for extra in conditions[1:]:
        condition = iuia.CreateOrCondition(condition, extra)
    return condition


def document_url(document: auto.Control) -> str:
    try:
        return document.GetValuePattern().Value or ""
    except Exception:
        return ""


def web_pages(window: auto.Control) -> list[WebPage]:
    """Every web document in the window (tabs, popups, iframes) with an http(s) URL."""
    pages = []
    for document in _find_all(window, _type_condition(auto.ControlType.DocumentControl)):
        url = document_url(document)
        if url.startswith(("https://", "http://")):
            pages.append(WebPage(url, document))
    return pages


def safe_name(control: auto.Control) -> str:
    try:
        return (control.Name or "").strip()
    except Exception:
        return ""


def buttons(root: auto.Control) -> list[auto.Control]:
    return _find_all(root, _type_condition(auto.ControlType.ButtonControl))


def find_button(root: auto.Control, labels: frozenset[str]) -> auto.Control | None:
    """First button whose accessible name equals one of labels (case-insensitive).

    Enabled buttons win, but a disabled match is still returned: consent pages
    disable their button while the window lacks focus (see wait_until_enabled).
    """
    matches = [b for b in buttons(root) if safe_name(b).casefold() in labels]
    return next((b for b in matches if is_enabled(b)), matches[0] if matches else None)


def find_button_matching(root: auto.Control, pattern) -> auto.Control | None:
    matches = [b for b in buttons(root) if pattern.search(safe_name(b))]
    return next((b for b in matches if is_enabled(b)), matches[0] if matches else None)


def wait_until_enabled(control: auto.Control, window: BrowserWindow, timeout: float = 3.0) -> bool:
    """Bring the window to the front if needed and wait for control to become enabled.

    claude.ai keeps "Authorize" disabled while its window is in the background
    (verified 2026-09-25), so a background tab cannot be authorized without focus.
    """
    if is_enabled(control):
        return True
    window.control.SetActive(waitTime=0)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if is_enabled(control):
            return True
    return False


def is_enabled(control: auto.Control) -> bool:
    try:
        return bool(control.IsEnabled)
    except Exception:
        return False


def _clickable_ancestor(control: auto.Control, stop_at: auto.Control, levels: int = 4):
    walker = _iuia().ControlViewWalker
    element = control.Element
    stop = stop_at.Element
    for _ in range(levels):
        try:
            element = walker.GetParentElement(element)
        except Exception:
            return None
        if not element or _iuia().CompareElements(element, stop):
            return None
        parent = auto.Control.CreateControlFromElement(element)
        if parent is not None and parent.ControlType in CLICKABLE_TYPES:
            return parent
    return None


def find_account_entry(root: auto.Control, email: str) -> auto.Control | None:
    """The clickable element that carries the given email (an account chooser row).

    Prefers a link/button whose own name contains the email; otherwise climbs
    from a text node with the email to its nearest clickable ancestor.
    """
    needle = email.casefold()
    for control in _find_all(root, _type_condition(*CLICKABLE_TYPES)):
        if needle in safe_name(control).casefold() and is_enabled(control):
            return control
    for text in _find_all(root, _type_condition(auto.ControlType.TextControl)):
        if needle in safe_name(text).casefold():
            ancestor = _clickable_ancestor(text, root)
            if ancestor is not None:
                return ancestor
    return None


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def page_emails(root: auto.Control) -> set[str]:
    """Every email address shown as text on the page, casefolded."""
    found = set()
    for text in _find_all(root, _type_condition(auto.ControlType.TextControl)):
        found.update(m.casefold() for m in _EMAIL.findall(safe_name(text)))
    return found


def clickable_names(root: auto.Control, limit: int = 40) -> list[str]:
    """Names of clickable controls on a page, for diagnostics when nothing matched."""
    names = [safe_name(c) for c in _find_all(root, _type_condition(*CLICKABLE_TYPES))]
    return [n for n in names if n][:limit]


def click(control: auto.Control) -> str:
    """Activate a control without stealing the mouse where possible. Returns the method used."""
    try:
        if control.GetPropertyValue(auto.PropertyId.IsInvokePatternAvailableProperty):
            control.GetInvokePattern().Invoke()
            return "invoke"
    except Exception:
        pass
    try:
        if control.GetPropertyValue(auto.PropertyId.IsLegacyIAccessiblePatternAvailableProperty):
            control.GetLegacyIAccessiblePattern().DoDefaultAction()
            return "default-action"
    except Exception:
        pass
    control.Click(simulateMove=False, waitTime=0.1)
    return "mouse"
