from urllib.parse import quote

import pytest

from anthropic_oauth_agent.policy import Step, classify, is_allowed_redirect

CLIENT = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTH_QUERY = (
    f"code=true&client_id={CLIENT}&response_type=code"
    "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
    "&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference"
    "&code_challenge=abc&code_challenge_method=S256&state=xyz"
)

# Captured from a real run on 2026-09-25 (login page reached from claude.com/cai/oauth/authorize).
LOGIN_URL = (
    "https://claude.ai/login?selectAccount=true&returnTo=%2Foauth%2Fauthorize%3Fcode%3Dtrue%26client_id%3D"
    "9d1c250a-e61b-44d9-88ed-5944d1962f5e%26response_type%3Dcode%26redirect_uri%3Dhttps%253A%252F%252F"
    "platform.claude.com%252Foauth%252Fcode%252Fcallback%26scope%3Dorg%253Acreate_api_key%2Buser%253Aprofile"
    "%2Buser%253Ainference%26code_challenge%3Dprobe%26code_challenge_method%3DS256%26state%3Dprobe"
)
GOOGLE_QUERY = (
    "access_type=offline&client_id=1062961139910-l2m55cb9h51u5cuc9c56eb3fevouidh9.apps.googleusercontent.com"
    "&display=popup&origin=https%3A%2F%2Fclaude.ai&prompt=select_account+consent&redirect_uri=gis_transform"
    "&response_type=code&scope=openid+profile+email&app_domain=https%3A%2F%2Fclaude.ai"
)


@pytest.mark.parametrize("url", [
    f"https://claude.ai/oauth/authorize?{AUTH_QUERY}",
    f"https://claude.com/cai/oauth/authorize?{AUTH_QUERY}",
    f"https://platform.claude.com/oauth/authorize?{AUTH_QUERY}",
    f"https://claude.ai/oauth/authorize?{AUTH_QUERY.replace('https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback', 'http%3A%2F%2Flocalhost%3A54545%2Fcallback')}",
])
def test_claude_code_authorize(url):
    assert classify(url) is Step.CLAUDE_AUTHORIZE


@pytest.mark.parametrize("url", [
    # someone else's OAuth client on the same page
    f"https://claude.ai/oauth/authorize?{AUTH_QUERY.replace(CLIENT, '00000000-0000-0000-0000-000000000000')}",
    # code sent to a foreign site
    f"https://claude.ai/oauth/authorize?{AUTH_QUERY.replace('platform.claude.com', 'evil.example')}",
    # look-alike hosts
    f"https://claude.ai.evil.example/oauth/authorize?{AUTH_QUERY}",
    f"https://evil.example/claude.ai/oauth/authorize?{AUTH_QUERY}",
    # plain http
    f"http://claude.ai/oauth/authorize?{AUTH_QUERY}",
    # not the authorize endpoint
    f"https://claude.ai/settings?{AUTH_QUERY}",
    "https://claude.ai/new",
    "https://example.com/",
    "",
])
def test_rejects_other_pages(url):
    assert classify(url) is None


def test_login_page_in_front_of_claude_code():
    assert classify(LOGIN_URL) is Step.CLAUDE_LOGIN


def test_login_page_for_anything_else_is_ignored():
    assert classify("https://claude.ai/login") is None
    assert classify("https://claude.ai/login?returnTo=%2Fnew") is None
    other = quote(f"/oauth/authorize?{AUTH_QUERY.replace(CLIENT, 'someone-else')}", safe="")
    assert classify(f"https://claude.ai/login?returnTo={other}") is None
    # returnTo pointing off-site must not count
    offsite = quote(f"https://evil.example/oauth/authorize?{AUTH_QUERY}", safe="")
    assert classify(f"https://claude.ai/login?returnTo={offsite}") is None


def test_google_steps_for_claude():
    assert classify(f"https://accounts.google.com/v3/signin/accountchooser?{GOOGLE_QUERY}") is Step.GOOGLE_CHOOSER
    assert classify(f"https://accounts.google.com/o/oauth2/auth/oauthchooseaccount?{GOOGLE_QUERY}") is Step.GOOGLE_CHOOSER
    assert classify(f"https://accounts.google.com/signin/oauth/id?{GOOGLE_QUERY}") is Step.GOOGLE_CONSENT
    assert classify(f"https://accounts.google.com/signin/oauth/v2/consent?{GOOGLE_QUERY}") is Step.GOOGLE_CONSENT
    assert classify(f"https://accounts.google.com/v3/signin/identifier?{GOOGLE_QUERY}") is Step.GOOGLE_SIGNED_OUT
    assert classify(f"https://accounts.google.com/v3/signin/challenge/pwd?{GOOGLE_QUERY}") is Step.GOOGLE_SIGNED_OUT


def test_google_claude_origin_only_in_nested_continue():
    inner = "https://accounts.google.com/signin/oauth/consent?" + GOOGLE_QUERY
    url = "https://accounts.google.com/v3/signin/accountchooser?continue=" + quote(inner, safe="")
    assert classify(url) is Step.GOOGLE_CHOOSER


def test_google_for_other_sites_is_ignored():
    other = "client_id=123.apps.googleusercontent.com&origin=https%3A%2F%2Fevil.example&redirect_uri=https%3A%2F%2Fevil.example%2Fcb"
    assert classify(f"https://accounts.google.com/v3/signin/accountchooser?{other}") is None
    assert classify(f"https://accounts.google.com/signin/oauth/consent?{other}") is None
    assert classify("https://accounts.google.com/") is None
    # look-alike origin
    spoof = other.replace("evil.example", "claude.ai.evil.example")
    assert classify(f"https://accounts.google.com/signin/oauth/consent?{spoof}") is None


@pytest.mark.parametrize("uri,ok", [
    ("http://localhost:1234/callback", True),
    ("http://127.0.0.1:9/callback", True),
    ("https://platform.claude.com/oauth/code/callback", True),
    ("http://localhost:1234/other", False),
    ("https://localhost:1234/callback", False),
    ("http://evil.example/callback", False),
    ("https://platform.claude.com/oauth/code/callback/../x", False),
    ("", False),
])
def test_redirects(uri, ok):
    assert is_allowed_redirect(uri) is ok
