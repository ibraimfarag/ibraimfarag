#!/usr/bin/env python3
"""Render a shields-style FOLLOWERS badge from the live GitHub profile page.

Why not use the REST API? Because GitHub's own numbers disagree: the API's
``followers`` field lags behind the counter rendered on the profile page
(measured: API = 24 while the page showed 27). The profile page is what
visitors actually see, so we read that first and fall back to the API only
if the markup changes.

Design notes:
  * This script never touches the filesystem. It writes the finished SVG to
    stdout and prints diagnostics to stderr, so the caller decides where the
    bytes land. That keeps all path handling out of the program entirely.
  * Every outbound request is checked against a fixed https host allow-list,
    so nothing in the environment can turn this into an SSRF probe.

Typical use:
    python scripts/followers_badge.py > assets/followers.svg
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

DEFAULT_USER = "ibraimfarag"

# The only hosts this script is ever allowed to contact.
ALLOWED_SCHEME = "https"
ALLOWED_HOSTS = frozenset({"github.com", "api.github.com"})

# GitHub usernames: 1-39 chars, alphanumeric and single hyphens.
USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")

UA = "Mozilla/5.0 (compatible; profile-badge-bot/1.0)"

# Visual language shared with the other README badges.
BG_LABEL = "#223444"
BG_VALUE = "#2c5364"
FG_LABEL = "#7fffd4"
FG_VALUE = "#ffffff"

FONT = "Verdana, DejaVu Sans, Geneva, sans-serif"
CHAR_W = 8.5  # px per char at 11px bold with letter-spacing

GITHUB_MARK = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 "
    "0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13"
    "-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66"
    ".07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15"
    "-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27"
    "c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 "
    "0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 "
    "0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
)


def read_username() -> str:
    """Return a validated GitHub username from the environment."""
    raw = os.environ.get("GH_USER", DEFAULT_USER).strip()
    if not USERNAME_RE.match(raw):
        raise SystemExit(f"refusing invalid GitHub username: {raw!r}")
    return raw


def fetch(url: str) -> str:
    """Fetch a URL, but only from the hard-coded allow-list of hosts."""
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme != ALLOWED_SCHEME:
        raise ValueError(f"blocked URL scheme: {parsed.scheme!r}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"blocked URL host: {parsed.hostname!r}")

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - host allow-listed
        return resp.read().decode("utf-8", "replace")


def followers_from_profile(user: str) -> int | None:
    """Scrape the publicly rendered follower count from the profile page."""
    page = fetch(f"https://github.com/{user}")
    patterns = (
        r'\?tab=followers".*?class="[^"]*text-bold[^"]*"[^>]*>\s*([\d,]+)\s*</span>\s*followers',
        r'\?tab=followers".*?>\s*([\d,]+)\s*</span>\s*followers',
        r'([\d,]+)\s*</span>\s*followers',
    )
    for pat in patterns:
        match = re.search(pat, page, re.S)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def followers_from_api(user: str) -> int:
    data = json.loads(fetch(f"https://api.github.com/users/{user}"))
    return int(data["followers"])


def render(label: str, value: str) -> str:
    """Build the badge SVG. Pure string work, no I/O."""
    label = label.upper()
    text_w_label = len(label) * CHAR_W
    text_w_value = len(value) * CHAR_W

    label_w = round(25 + text_w_label + 11)
    value_w = round(max(34, 17 + text_w_value))
    total = label_w + value_w
    height = 28

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{height}" role="img" aria-label="{label}: {value}">
  <title>{label}: {value}</title>
  <g shape-rendering="crispEdges">
    <rect width="{label_w}" height="{height}" fill="{BG_LABEL}"/>
    <rect x="{label_w}" width="{value_w}" height="{height}" fill="{BG_VALUE}"/>
  </g>
  <g transform="translate(8,8) scale(0.75)" fill="{FG_LABEL}">
    <path d="{GITHUB_MARK}"/>
  </g>
  <g fill="{FG_LABEL}" font-family="{FONT}" font-size="11" font-weight="700" letter-spacing="1.2">
    <text x="25" y="19" textLength="{text_w_label:.1f}" lengthAdjust="spacing">{label}</text>
  </g>
  <g fill="{FG_VALUE}" font-family="{FONT}" font-size="11" font-weight="700" letter-spacing="1.2">
    <text x="{label_w + 8}" y="19" textLength="{text_w_value:.1f}" lengthAdjust="spacing">{value}</text>
  </g>
</svg>
"""


def main() -> int:
    user = read_username()

    count: int | None = None
    source = "profile"

    try:
        count = followers_from_profile(user)
    except Exception as exc:  # network error, markup change, 404...
        print(f"profile scrape failed: {exc}", file=sys.stderr)

    if count is None:
        try:
            count = followers_from_api(user)
            source = "api"
        except Exception as exc:
            print(f"api fallback failed too: {exc}", file=sys.stderr)
            return 1

    print(f"source={source} followers={count}", file=sys.stderr)
    sys.stdout.write(render("followers", str(count)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
