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

## Setup

```bash
git clone https://github.com/Olalolo22/3riage.git
cd 3riage
pip install -r requirements.txt

cp .triage.env.example .triage.env
# Edit .triage.env and set GITHUB_USERNAME and GITHUB_TOKEN
```

**Token scopes needed (classic token):** `repo` (read), `read:org`, `read:user`
Use a read-only token. The fork action uses your local `gh` CLI separately.

## Usage

```bash
python triage.py                    # full report
python triage.py --mode prs         # PR buckets only
python triage.py --mode issues      # unlinked issues & bounty bids only
python triage.py --mode claims      # recently merged, ready to claim
python triage.py --mode forks       # fork status report
python triage.py --forks            # interactive fork assistant
python triage.py --repo owner/repo  # filter to one repo
python triage.py --json             # raw JSON (pipe-friendly)
python triage.py --include-drafts   # include draft PRs
python triage.py --min-age-hours 2  # ignore comments younger than 2h
python triage.py --claims-days 30   # look back 30 days for merged PRs
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

## Testing

The decision engine in `core.py` is pure logic with zero network dependencies:

```bash
python3 -m unittest discover tests
```

## Configuration (`.triage.env`)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_USERNAME` | required | Your GitHub username |
| `GITHUB_TOKEN` | required | Read-only GitHub token (or set via `gh auth`) |
| `TRIAGE_INCLUDE_DRAFTS` | `false` | Include draft PRs (overridden by `--include-drafts`) |
| `TRIAGE_IGNORE_BOTS` | `true` | Skip bot comments when calculating activity |
| `TRIAGE_IGNORE_REPOS` | — | Comma-separated repos to exclude |
| `TRIAGE_ONLY_REPOS` | — | Comma-separated repos to limit to |
| `TRIAGE_MIN_AGE_HOURS` | `0` | Ignore activity younger than N hours (overridden by `--min-age-hours`) |

## Project structure

```
github-triage/
├── core.py            # detection logic — returns JSON, no I/O
├── github_client.py   # GraphQL + minimal REST client
├── triage.py          # CLI presentation layer
├── tests/
│   └── test_core.py   # unit test suite (26 table-driven tests)
├── .triage.env.example
├── requirements.txt
└── README.md
```

## Roadmap

- [ ] Web dashboard (Flask, same JSON engine)
- [ ] `--mode claims` Discord/Drips link column
- [ ] AI comment classifier (v2 stub already in `core.py`)
- [ ] Date-based snooze (local SQLite)
- [ ] Daily digest (Discord/Slack webhook)

