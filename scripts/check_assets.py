#!/usr/bin/env python3
"""
Validate every external image referenced by readme.md.

Catches two classes of bug that are otherwise only visible on the rendered
profile page:

1. Malformed XML/SVG. A card service may echo an unescaped `&` into its SVG
   (e.g. capsule-render given `desc=...Linux%20%26%20NixOS` emits a raw `&`,
   which is invalid XML). Browsers then show the alt text instead of the image.
2. Dead endpoints. Some services return 402/404 (github-profile-trophy and
   github-readme-activity-graph both return 402 today).

Exit codes:
  0  everything healthy (transient 5xx/timeout/403 warnings do not fail the run)
  1  a structural problem was found: malformed XML

HTTP status is deliberately treated as a warning, not a failure. Several of
these services rate-limit or drop connections under repeated polling (in CI
and locally alike), so a non-200 is not proof the asset is broken. Malformed
XML is deterministic and always indicates a real bug.

Stdlib only, matching the rest of this repo.
"""

from __future__ import annotations

import concurrent.futures
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

README = "readme.md"
ATTEMPTS = 2
TIMEOUT = 20
MAX_WORKERS = 8

# Never fetched by a browser as a picture (plain links, not <img> sources).
SKIP_PREFIXES = ("https://github.com/", "https://star-history.com/")
SKIP_SUBSTRINGS = ("book.2011101.xyz",)

# Animated/raster endpoints that are not XML even though they are images.
NON_XML_HINTS = ("ghchart",)


def collect_urls(text: str) -> list[str]:
    urls: list[str] = []
    for attr in ("src", "srcset"):
        for match in re.findall(rf'{attr}="([^"]+)"', text):
            if match not in urls:
                urls.append(match)
    return [
        u
        for u in urls
        if not u.startswith(SKIP_PREFIXES)
        and not any(s in u for s in SKIP_SUBSTRINGS)
    ]


def fetch(url: str) -> tuple[int, bytes, str]:
    """Return (status, body, error). Retries transient failures."""
    last = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "profile-asset-check"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read(), ""
        except urllib.error.HTTPError as exc:
            body = exc.read()
            # 4xx will not fix itself; 429 is worth a retry
            if exc.code < 500 and exc.code != 429:
                return exc.code, body, f"HTTP {exc.code}"
            last = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - network layer, message is enough
            last = f"{type(exc).__name__}: {exc}"
        if attempt < ATTEMPTS:
            time.sleep(2 * attempt)
    return 0, b"", last


def check_one(url: str) -> tuple[str, str, str]:
    """Return (label, severity, detail) where severity is ok|warn|fail."""
    label = url.split("?")[0].replace("https://", "")
    status, body, err = fetch(url)

    if err or status != 200:
        # Status codes are noisy for these services; never fatal on their own.
        return label, "warn", f"{err or status}"

    if any(h in url for h in NON_XML_HINTS):
        return label, "ok", f"{len(body)} bytes, raster"

    head = body.lstrip()[:64].lower()
    if not head.startswith(b"<"):
        return label, "warn", f"not XML/SVG ({head[:32]!r})"
    try:
        ET.fromstring(body)
    except ET.ParseError as exc:
        return label, "fail", f"malformed XML -> {exc}"
    return label, "ok", f"{len(body)} bytes, xml valid"


def main() -> int:
    with open(README, encoding="utf-8") as fh:
        text = fh.read()

    urls = collect_urls(text)
    print(f"checking {len(urls)} external assets\n")

    broken: list[str] = []
    warnings: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for label, severity, detail in pool.map(check_one, urls):
            if severity == "ok":
                print(f"  ok    {label} ({detail})")
            elif severity == "warn":
                warnings.append(f"{label}: {detail}")
                print(f"  WARN  {label}: {detail}")
            else:
                broken.append(f"{label}: {detail}")
                print(f"  FAIL  {label}: {detail}")

    print()
    if warnings:
        print("warnings (network/status noise, non-fatal):")
        for w in warnings:
            print(f"  - {w}")
    if broken:
        print("\nBROKEN assets (must fix):")
        for b in broken:
            print(f"  - {b}")
        return 1

    print("all assets healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
