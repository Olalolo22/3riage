# 3riage

> **GitHub tells you what changed. 3riage tells you who has the next move.**

A contributor-first triage engine. Shows everything on GitHub waiting for your attention — PRs where the ball is in your court, issues you applied to with no PR yet, repos you haven't forked, and recently merged PRs ready to claim on Discord/Drips.

## What it does that GitHub doesn't

| Problem | GitHub's limitation | 3riage |
|---|---|---|
| Issues you applied to but haven't PR'd | Flat list, no relational state | Crosses `involves:@me` against your open PRs, distinguishes active bids from outbid issues |
| "Ball in your court" PR detection | `Changes Requested` badge stays forever | Compares last commit date vs review timestamp per reviewer |
| Multi-reviewer deadlocks | Single review status masks others | Analyzes reviews per reviewer so one approval cannot mask an unresolved block |
| Unforked repos you're assigned on | Invisible | Diffs your forks against assigned repos |
| Recently merged PRs to claim | No view | "Ready to Claim" shelf (last 14 days) |

## Quickstart (CLI + Local Web Dashboard)

If you already have the [`gh` CLI](https://cli.github.com/) logged in (`gh auth login`), **zero configuration is needed** — `3riage` automatically uses `gh auth token` and resolves your username via `viewer { login }`:

```bash
# Install with pipx or uv
pipx install git+https://github.com/Olalolo22/3riage.git@4public
# or run ephemerally with uvx
uvx --from git+https://github.com/Olalolo22/3riage.git@4public 3riage

# Launch the local web dashboard
3riage ui
```

Or run from a local clone:

```bash
git clone https://github.com/Olalolo22/3riage.git
cd 3riage
pip install -r requirements.txt
pip install -e .

# Optional if `gh auth login` is already set up:
cp .triage.env.example .triage.env
# Edit .triage.env and set GITHUB_TOKEN (and optionally GITHUB_USERNAME)
```

**Token scopes needed (classic token):** `repo` (read), `read:org`, `read:user`
Use a read-only token. The local fork action uses your local `gh` CLI separately.

## Usage

```bash
3riage                    # full CLI report (or `python triage.py`)
3riage ui                 # launch local web dashboard on 127.0.0.1:5000
3riage ui --demo          # launch dashboard in sandbox demo mode
3riage --mode prs         # PR buckets only
3riage --mode issues      # unlinked issues & bounty bids only
3riage --mode claims      # recently merged, ready to claim
3riage --mode forks       # fork status report
3riage --forks            # interactive fork assistant
3riage --repo owner/repo  # filter to one repo
3riage --json             # raw JSON (pipe-friendly)
3riage --include-drafts   # include draft PRs
3riage --min-age-hours 2  # ignore comments younger than 2h
3riage --claims-days 30   # look back 30 days for merged PRs
```

## How PR bucketing works

```
NEEDS_YOU      — An unaddressed CHANGES_REQUESTED review exists without a subsequent commit,
                 OR their newest activity is newer than yours.
WAITING_ON_THEM — Your activity is newer than theirs (you pushed fixes or opened a clean PR).
PROBABLY_FINE  — All reviews are APPROVED, or the latest maintainer comment is a sign-off (LGTM).
```

### Multi-Reviewer Awareness
GitHub reviews are evaluated **per reviewer**. If Reviewer A requests changes and Reviewer B approves later, the PR remains `NEEDS_YOU` until you push a commit addressing Reviewer A's feedback.

### Bot Filtering & AI Reviewers
- **Hygiene & CI Bots:** Automated accounts like `dependabot`, `github-actions`, `stale`, and CI bots are filtered out by default when `TRIAGE_IGNORE_BOTS=true`.
- **AI Code Reviewers:** Automated reviewers like `@coderabbitai` and `@copilot-pull-request-reviewer` are **intentionally not ignored**. For personal projects, bounties, and learning, their actionable comments act like mentor reviews requiring your input. (If you ever want to treat them as background noise, add their logins to `IGNORE_BOT_LOGINS` in `github_client.py`).

## Self-Hosting

You can deploy 3riage publicly on **Vercel** (or any WSGI host) in three modes:
1. **Sandbox Demo Mode (Zero Config):** Deploying without credentials automatically boots into the curated sample dataset (`mock_data.py`).
2. **Public Multi-User Mode (GitHub App / OAuth):** Visitors click **Connect GitHub** to sign in via an encrypted `HttpOnly` cookie session.
   * Create a **GitHub App** with **zero repository permissions** (gives implicit read-only access to public PRs, issues, reviews, and forks across any org without requiring installation on external repos).
   * Set Callback URL to `https://<your-domain>/api/auth/callback` (and `http://127.0.0.1:5000/api/auth/callback` for local testing).
   * Set the following environment variables on Vercel:
     * `GITHUB_OAUTH_CLIENT_ID`
     * `GITHUB_OAUTH_CLIENT_SECRET`
     * `SESSION_SECRET` (generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`)
3. **Private Single-User Mode:** Set `GITHUB_TOKEN` (and optionally `GITHUB_USERNAME`) in `.triage.env` or Vercel environment variables.

## Testing

The decision engine, mock dataset, OAuth cookie security, and multi-user cache isolation are unit-tested with zero network dependencies:

```bash
python3 -m unittest discover tests
```

## Configuration (`.triage.env`)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_USERNAME` | auto (`viewer`) | Your GitHub username (auto-resolved from token if omitted) |
| `GITHUB_TOKEN` | `gh auth token` | Read-only GitHub token (or set via `gh auth`) |
| `TRIAGE_INCLUDE_DRAFTS` | `false` | Include draft PRs (overridden by `--include-drafts`) |
| `TRIAGE_IGNORE_BOTS` | `true` | Skip bot comments when calculating activity |
| `TRIAGE_IGNORE_REPOS` | — | Comma-separated repos to exclude |
| `TRIAGE_ONLY_REPOS` | — | Comma-separated repos to limit to |
| `TRIAGE_MIN_AGE_HOURS` | `0` | Ignore activity younger than N hours (overridden by `--min-age-hours`) |
| `GITHUB_OAUTH_CLIENT_ID` | — | GitHub App / OAuth App client ID for public web login |
| `GITHUB_OAUTH_CLIENT_SECRET` | — | GitHub App / OAuth App client secret |
| `SESSION_SECRET` | — | Secret for Fernet-encrypted `HttpOnly` session cookies |

## Project structure

```
3riage/
├── core.py            # pure decision engine — returns JSON, no I/O
├── github_client.py   # GraphQL + minimal REST client
├── triage.py          # CLI (`3riage` & `3riage ui`)
├── auth.py            # GitHub App / OAuth + Fernet-encrypted cookie sessions
├── app.py             # Flask web dashboard + per-user cache
├── mock_data.py       # curated sandbox dataset for zero-credential demo mode
├── api/               # Vercel Python serverless endpoints
├── static/ & templates/ & public/  # Linear-style responsive web dashboard
├── tests/             # unit test suite
├── pyproject.toml     # pipx / uvx / pip package configuration
└── vercel.json
```

## Roadmap

- [x] Web dashboard (Flask + Vercel, same JSON engine)
- [x] Sandbox demo mode + GitHub App / OAuth multi-user support
- [x] Packaged CLI (`3riage` + `3riage ui` with `gh` auto-detection)
- [ ] `--mode claims` Discord/Drips link column
- [ ] AI comment classifier (v2 stub already in `core.py`)
- [ ] Date-based snooze (local SQLite)
- [ ] Daily digest (Discord/Slack webhook)
