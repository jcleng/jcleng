#!/usr/bin/env python3
"""
Regenerate the <!--AUTO:...--> blocks in readme.md from the live GitHub API.

Only the Python standard library is used, so the workflow needs no pip install.
Every block is written between matching markers:

    <!--AUTO:NAME-->
    ...generated content...
    <!--/AUTO:NAME-->

Content outside the markers is never touched. If a block fails to build it is
left exactly as-is and the failure is reported, so a partial API outage can
never blank out the profile.

Auth:  GITHUB_TOKEN env var (the workflow passes secrets.GITHUB_TOKEN).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

LOGIN = "jcleng"
README = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "readme.md")
README = os.path.normpath(README)

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

# how many languages / repos to render
LANG_COUNT = 9
FEATURED_COUNT = 8
# bar geometry
LANG_BAR = 28
LANG_SCALE = 40.0  # a language at 40% of all bytes fills the whole bar
YEAR_BAR = 34

errors: list[str] = []


# --------------------------------------------------------------------------- #
# http helpers
# --------------------------------------------------------------------------- #
def _token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        sys.exit("error: GITHUB_TOKEN is not set")
    return tok


def _request(url: str, data: bytes | None = None, attempts: int = 4) -> dict:
    """GET/POST JSON with retries on transient network and 5xx failures."""
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{LOGIN}-profile-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 4xx other than rate limiting will not fix themselves
            if exc.code < 500 and exc.code != 429:
                detail = exc.read().decode("utf-8", "replace")[:300]
                raise RuntimeError(f"HTTP {exc.code} on {url}: {detail}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc

        if attempt < attempts:
            wait = 2**attempt
            print(f"  retry {attempt}/{attempts - 1} after {wait}s ({last})", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"request failed after {attempts} attempts: {url} ({last})")


def rest(path: str) -> dict | list:
    return _request(f"{API}{path}")


def graphql(query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    out = _request(GRAPHQL, payload)
    if out.get("errors"):
        raise RuntimeError(f"graphql errors: {out['errors']}")
    return out["data"]


def paged_repos() -> list[dict]:
    """All repositories owned by LOGIN (paginated)."""
    repos: list[dict] = []
    page = 1
    while True:
        chunk = rest(f"/users/{LOGIN}/repos?per_page=100&type=owner&page={page}")
        if not isinstance(chunk, list) or not chunk:
            break
        repos.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return repos


# --------------------------------------------------------------------------- #
# display helpers
# --------------------------------------------------------------------------- #
def dwidth(text: str) -> int:
    """Terminal display width: CJK / emoji count as 2 columns."""
    w = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad(text: str, width: int) -> str:
    """Pad to a display width, truncating with an ellipsis if too long."""
    text = text.replace("\n", " ").replace("|", "/").strip()
    if dwidth(text) > width:
        while text and dwidth(text) > width - 1:
            text = text[:-1]
        text = text.rstrip() + "…"
    return text + " " * max(0, width - dwidth(text))


def bar(value: float, maximum: float, width: int, fill: str, empty: str) -> str:
    if maximum <= 0:
        return empty * width
    n = round(value / maximum * width)
    n = max(0, min(width, n))
    return fill * n + empty * (width - n)


# --------------------------------------------------------------------------- #
# blocks
# --------------------------------------------------------------------------- #
def block_profile(user: dict, repos: list[dict]) -> str:
    """operator.conf box + a live repo/star counter."""
    created = user["created_at"][:4]
    years = int(user["updated_at"][:4]) - int(created)

    own = [r for r in repos if not r["fork"]]

    # Rank languages by how many repositories use them (not by API order).
    tally: dict[str, int] = {}
    for repo in own:
        lang = repo.get("language")
        if lang:
            tally[lang] = tally.get(lang, 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    stack = " · ".join(name for name, _ in ranked[:5]) or "code"

    loc = user.get("location") or "Earth"

    rows = [
        ("OPERATOR", user["login"]),
        ("LOCATION", loc),
        ("UPTIME", f"coding since {created}  ·  {years} yrs in the terminal"),
        ("OS", "NixOS  ·  Arch  ·  Linux  (daily driver)"),
        ("SHELL", "zsh  +  tmux  +  nvim"),
        ("STACK", stack),
        ("INTERESTS", "self-hosted · flatpak · homelab · AI agents"),
        ("PHILOSOPHY", '"Automate it, containerize it, self-host it."'),
    ]

    # inner = pad width. Row = "  │  " (5) + inner + "│" (1) = inner + 6.
    # Border = "  ┌" (3) + dashes + "┐" (1), so dashes = inner + 2.
    inner = 61
    lines = ["  ┌" + "─" * (inner + 2) + "┐"]
    for key, val in rows:
        lines.append("  │  " + pad(f"{key:<10}:  {val}", inner) + "│")
    lines.append("  └" + "─" * (inner + 2) + "┘")

    box = "\n".join(lines)
    return (
        "```console\n"
        "jcleng@github:~$ cat /etc/profile.d/operator.conf\n"
        "\n"
        f"{box}\n"
        "\n"
        "jcleng@github:~$ ./stats.sh --all\n"
        "```\n"
    )


def block_langmatrix(repos: list[dict]) -> str:
    """Language shares from real Linguist byte counts (GraphQL languages)."""
    nodes = [r for r in repos if not r["fork"]]
    if not nodes:
        raise RuntimeError("no repositories to scan")

    query = """
    query($login:String!){
      user(login:$login){
        repositories(first:100,ownerAffiliations:OWNER,isFork:false){
          nodes{
            name
            languages(first:12,orderBy:{field:SIZE,direction:DESC}){
              totalSize edges{ size node{ name } }
            }
          }
        }
      }
    }
    """
    data = graphql(query, {"login": LOGIN})
    agg: dict[str, int] = {}
    total = 0
    for node in data["user"]["repositories"]["nodes"]:
        langs = node["languages"]
        total += langs["totalSize"]
        for edge in langs["edges"]:
            agg[edge["node"]["name"]] = agg.get(edge["node"]["name"], 0) + edge["size"]
    if not total:
        raise RuntimeError("linguist returned no bytes")

    top = sorted(agg.items(), key=lambda kv: -kv[1])[:LANG_COUNT]
    body = []
    for name, size in top:
        pct = size / total * 100
        body.append(
            f"  {name:<12}{pct:5.1f}%  "
            f"{bar(pct, LANG_SCALE, LANG_BAR, '█', '░')}"
        )
    return "```text\n" + "\n".join(body) + "\n```\n"


def block_yearly() -> str:
    """Contribution totals per year from the contributions calendar."""
    query = """
    query($login:String!,$from:DateTime!,$to:DateTime!){
      user(login:$login){
        contributionsCollection(from:$from,to:$to){
          contributionCalendar{ totalContributions }
        }
      }
    }
    """
    this_year = int(
        os.environ.get("PROFILE_YEAR") or datetime.date.today().year
    )
    start_year = this_year - 5

    years: list[tuple[int, int]] = []
    for year in range(start_year, this_year + 1):
        data = graphql(
            query,
            {
                "login": LOGIN,
                "from": f"{year}-01-01T00:00:00Z",
                "to": f"{year}-12-31T23:59:59Z",
            },
        )
        total = data["user"]["contributionsCollection"]["contributionCalendar"][
            "totalContributions"
        ]
        years.append((year, total))

    peak = max((t for _, t in years), default=0)
    lines = []
    for year, total in years:
        mark = ""
        if total and total == peak:
            mark = "   ← peak"
        elif year == this_year:
            mark = "   ← this year"
        lines.append(
            f"  {year}  {total:>4}  {bar(total, peak, YEAR_BAR, '▇', '·')}{mark}"
        )
    return "```text\n" + "\n".join(lines) + "\n```\n"


def clean_desc(desc: str, width: int = 52) -> str:
    """Tidy a repo description: drop links, collapse space, fit the column."""
    desc = desc or ""
    desc = re.sub(r"https?://\S+", "", desc)  # bare URLs add no value here
    desc = re.sub(r"\s+", " ", desc).strip(" \u2014-·|,")
    if not desc:
        return "—"
    if dwidth(desc) > width:
        while desc and dwidth(desc) > width - 1:
            desc = desc[:-1]
        desc = desc.rstrip(" ,;·-") + "…"
    return desc


def block_featured(repos: list[dict]) -> str:
    """Top repositories by stars.

    Archived repos are kept on purpose: read-only does not mean worthless, and
    the most-starred projects here are archived. The profile repo itself and
    `awesome-*` link dumps are excluded.
    """
    own = [
        r
        for r in repos
        if not r["fork"]
        and r["name"] != LOGIN
        and not r["name"].startswith("awesome-")
    ]

    # Prefer repos that earned a star; fill any gap with the freshest work.
    starred = sorted(
        (r for r in own if r["stargazers_count"] > 0),
        key=lambda r: (-r["stargazers_count"], r["name"]),
    )
    picked = list(starred)
    if len(picked) < FEATURED_COUNT:
        rest = sorted(
            (r for r in own if r["stargazers_count"] == 0 and r.get("description")),
            key=lambda r: r["pushed_at"],
            reverse=True,
        )
        picked.extend(rest[: FEATURED_COUNT - len(picked)])
    picked = picked[:FEATURED_COUNT]

    out = [
        "| ★ | Repository | Stack | What it is |",
        "|:---:|---|---|---|",
    ]
    for r in picked:
        desc = clean_desc(r.get("description"))
        lang = r.get("language") or "—"
        url = r["html_url"]
        out.append(
            f"| **{r['stargazers_count']}** | [{r['name']}]({url}) "
            f"| `{lang}` | {desc} |"
        )
    return "\n".join(out) + "\n"


def block_repocount(repos: list[dict]) -> str:
    own = [r for r in repos if not r["fork"]]
    stars = sum(r["stargazers_count"] for r in own)
    # forks received on my own repos (not the count of repos I forked)
    forks = sum(r["forks_count"] for r in own)
    return (
        f"<sub>`{len(own)}` original repositories · `{stars}` stars earned "
        f"· `{forks}` forks received</sub>\n"
    )


BLOCKS = {
    "PROFILE": lambda u, r: block_profile(u, r),
    "LANGMATRIX": lambda u, r: block_langmatrix(r),
    "YEARLY": lambda u, r: block_yearly(),
    "FEATURED": lambda u, r: block_featured(r),
    "REPOCOUNT": lambda u, r: block_repocount(r),
}


# --------------------------------------------------------------------------- #
# marker replacement
# --------------------------------------------------------------------------- #
def replace_block(text: str, name: str, content: str) -> str:
    pattern = re.compile(
        rf"(<!--AUTO:{name}-->)(.*?)(<!--/AUTO:{name}-->)",
        re.DOTALL,
    )
    if not pattern.search(text):
        errors.append(f"marker {name} not found in readme.md")
        return text
    return pattern.sub(lambda m: f"{m.group(1)}\n{content}{m.group(3)}", text, count=1)


def main() -> int:
    with open(README, encoding="utf-8") as fh:
        original = fh.read()
    text = original

    user = rest(f"/users/{LOGIN}")
    repos = paged_repos()
    print(f"fetched {len(repos)} repositories for {LOGIN}")

    for name, builder in BLOCKS.items():
        try:
            content = builder(user, repos)
        except Exception as exc:  # keep the old block, report, continue
            errors.append(f"{name}: {exc}")
            print(f"  !! {name} failed: {exc}")
            continue
        before = text
        text = replace_block(text, name, content)
        state = "updated" if text != before else "unchanged"
        print(f"  ok {name}: {state}")

    if text != original:
        with open(README, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("readme.md written")
    else:
        print("readme.md already up to date")

    if errors:
        print("\ncompleted with warnings:")
        for err in errors:
            print(f"  - {err}")
        # Only fail hard when nothing could be produced at all.
        if text == original and any("not found" in e for e in errors):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
