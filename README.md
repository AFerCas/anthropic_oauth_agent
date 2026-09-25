# anthropic_oauth_agent

Watches every open browser on this Windows machine for the Claude Code login
(`claude` / `/login`) and clicks through it as the Google account set in `local.toml`:

1. claude.ai login page: clicks "Continue with Google" ("Mit Google fortfahren").
2. Google account chooser: clicks the row with your email.
3. Google "continue to Claude" confirmation, if shown: clicks Continue / Weiter.
4. Claude Code authorize page: clicks Authorize, but only when the page says
   "Logged in as" followed by your email. If another account is shown, it clicks "Switch
   account" instead. The button is disabled while the browser window is in the
   background, so the agent brings that window to the front first.

It reads pages through Windows UI Automation, so it works with the browsers you
already have open (Chrome, Edge, Vivaldi, Brave, Opera, Firefox). No extension,
no remote-debugging port, no browser restart, and no passwords are stored or typed.

## Setup

Copy `local.example.toml` to `local.toml` and set `email` to your Google account.
`local.toml` is gitignored, so your address stays out of the repo. `--email` overrides it.

## Run

```powershell
uv sync
uv run anthropic-oauth-agent            # foreground, Ctrl+C to stop
uv run anthropic-oauth-agent --dry-run  # log what it would click, click nothing
uv run anthropic-oauth-agent --list     # show browser windows, page URLs and how each is classified
.\start-agent.cmd                       # background (no console window)
.\stop-agent.cmd
```

The log is in `logs/agent.log`. Only one agent runs at a time, enforced by a named mutex.

To start it at every logon, run `.\install-autostart.ps1` once. It puts a
shortcut to `start-agent.cmd` in your Startup folder; `-Remove` takes it out again.

## What it will and will not click

The agent never clicks anything just because a button label matches. The page URL
has to pass these gates in `src/anthropic_oauth_agent/policy.py`:

| Page | Condition |
| --- | --- |
| Authorize | `https` on claude.ai / claude.com / platform.claude.com / console.anthropic.com, path `/oauth/authorize`, `client_id` = Claude Code's (`9d1c250a-…`), `response_type=code`, `redirect_uri` = localhost `/callback` or the platform.claude.com code callback |
| Claude login | same hosts, path `/login`, and its `returnTo` is an authorize URL that passes the row above |
| Google | `accounts.google.com`, and the request is for claude.ai (claude.ai's Google `client_id`, or `origin` / `app_domain` / `redirect_uri` on an Anthropic host). Also only within 5 minutes of a Claude Code login or authorize page being seen |

If Google asks for an email or password, the agent stops and logs it. Sign in to
Google once by hand in that browser, and later logins will be fully automatic.

## How it works

- `uia.py`: lists top-level windows of known browser processes. Only windows whose
  title looks like a login (Claude, Google, sign in, …) are inspected, which keeps
  the one-second idle loop cheap. Chromium builds its accessibility tree only when
  asked, so each inspected window first gets a `WM_GETOBJECT`. Every web document
  in the window then reports its full URL through its UIA value. Clicks use UIA
  Invoke, so the mouse is not moved.
- `policy.py`: pure URL classification, covered by `tests/test_policy.py`.
- `agent.py`: the loop. A page is clicked at most 3 times, at least 8 s apart,
  unless it navigates away.
- `config.py`: target email (read from `local.toml`), client ids, hosts and button labels (English and German).

## Test

```powershell
uv run pytest                                   # URL policy
$env:ANTHROPIC_OAUTH_AGENT_LIVE = "1"; uv run pytest  # plus real Chrome against tests/fixtures
```

Verified on 2026-09-25 against the live pages:
- Chrome 153 (fresh profile): the Claude login page was detected and "Mit Google
  fortfahren" clicked. Google's sign-in form was recognised as signed out and left alone.
- Vivaldi 8.2 (signed in to claude.ai): the authorize page was detected, and a dry run
  found `Authorize` next to "Logged in as" and the configured email. `Authorize` is disabled while
  the window is in the background and becomes enabled once the window is in front.
- The Google account chooser step is covered only by the fixture test. No browser was
  signed out of claude.ai to test it against the real Google page.

## Known limits

- Button labels for the Claude authorize page and Google's consent page are
  English/German guesses (`config.py`). When a page is recognised but no button
  matches, the log lists the page's clickable elements, so the missing label can be added.
- Chrome may build the tree of a window only once it has been in the foreground.
  The login tab normally opens in the foreground, so this rarely matters.
- If Chrome's FedCM account dialog replaces Google's popup, that dialog is browser
  UI rather than a web page and is not handled.
