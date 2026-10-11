# jcleng — GitHub Profile README

Self-updating GitHub profile (`github.com/jcleng`). The README is a neon-terminal
dashboard whose data blocks are regenerated from the GitHub API by a scheduled
workflow. Nothing inside an `<!--AUTO:...-->` marker should be hand-edited.

## Layout

```
readme.md                              the profile page (generated blocks inside markers)
scripts/update_profile.py              regenerates every AUTO block (stdlib only)
scripts/check_assets.py                validates every external image URL
.github/workflows/update-profile.yml   refresh every 12h + on demand
.github/workflows/snake.yml            contribution snake -> `output` branch
.github/keepalive.txt                  marker committed only when the repo goes idle
```

## Key Commands

```bash
# Regenerate all AUTO blocks locally (needs a token with repo read access)
export GITHUB_TOKEN=$(gh auth token)
python3 scripts/update_profile.py

# Validate every external image (XML well-formedness + reachability)
python3 scripts/check_assets.py

# Preview what the workflow would commit
git diff readme.md

# Trigger the refresh workflow on demand
gh workflow run update-profile.yml -R jcleng/jcleng

# Trigger the snake workflow on demand
gh workflow run snake.yml -R jcleng/jcleng

# Check recent runs
gh run list -R jcleng/jcleng -L 5
```

The script is idempotent: running it twice with no upstream change prints
`readme.md already up to date` and writes nothing.

## AUTO Blocks

Each block lives between `<!--AUTO:NAME-->` and `<!--/AUTO:NAME-->`. The script
replaces only the content between markers; everything else is untouched.

| Block | Source | Notes |
|---|---|---|
| `PROFILE` | REST `/users/{login}` + repo list | operator.conf box; `UPTIME` years and `STACK` are derived |
| `LANGMATRIX` | GraphQL `languages` (Linguist bytes) | public non-fork repos only, paginated |
| `YEARLY` | GraphQL `contributionsCollection` | last 6 calendar years |
| `FEATURED` | REST repo list | top by stars; excludes this repo and `awesome-*` |
| `REPOCOUNT` | REST repo list | original repos / stars earned / forks received |

### Adding or changing a block

1. Add `<!--AUTO:NAME-->` … `<!--/AUTO:NAME-->` to `readme.md`.
2. Write a `block_<name>(user, repos) -> str` builder in `scripts/update_profile.py`.
3. Register it in the `BLOCKS` dict.

A builder returns the exact text to place between the markers. If a builder
raises, the old block is kept and the failure is reported — a partial API outage
never blanks the profile.

## Design Rules

- **Neon terminal theme.** Background `#0D1117`, accent `#00FF41`, text `#C9D1D9`.
  Keep new cards on the same palette.
- **Public data only.** Language stats use `privacy:PUBLIC` so a maintainer token
  and CI's `GITHUB_TOKEN` produce identical output. Without it, private repos
  leak into the numbers and local/CI results diverge.
- **ASCII alignment.** Box rows are padded by display width, where CJK and emoji
  count as two columns (`dwidth`/`pad`). Verify alignment after editing the box.
- **stdlib only.** No pip install in CI; do not add third-party imports.
- **Fail soft.** Retries for transient network/5xx errors; 4xx fails fast.
- **Never nest HTML comments.** HTML comments do not nest: the first `-->`
  closes the comment. Writing a literal `<!--AUTO:...-->` inside another comment
  ends it early and leaks the remaining lines onto the profile page. AUTO markers
  must always sit outside other comments. `check_comment_nesting()` in the script
  fails the run if this happens.
- **Escape `&` in card parameters.** Query strings are URL-decoded by the card
  service, which then interpolates the value into its SVG. A literal `&` in a
  parameter (e.g. `desc=Linux%20%26%20NixOS`) is emitted unescaped and makes the
  SVG invalid XML, so the browser shows the `alt` text instead of the image.
  Use `+` (`Linux%20%2B%20NixOS`) or another wording. `check_assets.py` catches
  this by parsing each asset as XML.

## Workflow Notes

- **Scheduling.** `update-profile.yml` runs at 02:00 and 14:00 UTC. Both workflows
  also support `workflow_dispatch`.
- **Keep-alive.** GitHub disables scheduled workflows after 60 days of repository
  inactivity. When the repo has been idle for 30+ days, the scheduled run
  rewrites `.github/keepalive.txt` so the workflows stay enabled. `.github/keepalive.txt`
  must exist because the commit step references it by path.
- **No push loops.** Auto-commits use `[skip ci]`. `snake.yml` only triggers on
  push to its own file, not on every `main` push, so README refreshes do not
  re-run the snake.
- **Permissions.** Both workflows need `contents: write` to push.

## Third-party Assets

Rendered live by external services and cached by them, so they need no workflow:

`capsule-render`, `readme-typing-svg`, `skillicons`, `github-readme-stats`,
`streak-stats`, `github-profile-summary-cards`, `ghchart`, `star-history`,
`komarev` (view counter), plus `shields.io` badges.

`github-profile-trophy` and `github-readme-activity-graph` return HTTP 402 and are
deliberately not used. Verify a service with `curl` before adding a card.

## Commit Conventions

- Hand-written changes: normal conventional commits (`feat:`, `fix:`, `docs:`).
- Automated refreshes: `chore: auto-update profile README [skip ci]`.
- Do not edit files on the `output` branch by hand; it is generated by `snake.yml`.
