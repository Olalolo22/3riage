# 3riage

A personal GitHub contribution triage tool. Shows everything on GitHub waiting for your attention — PRs where the ball is in your court, issues you're involved in with no PR yet, repos you haven't forked, and recently merged PRs ready to claim on Discord/Drips.

## What it does that GitHub doesn't

| Problem | GitHub's limitation | 3riage |
|---|---|---|
| Issues you applied to but haven't PR'd | Flat list, no cross-reference | Crosses `involves:@me` against your open PRs |
| "Ball in your court" PR detection | `Changes Requested` badge stays forever | Compares last commit date vs review timestamp |
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
python triage.py --mode issues      # unlinked issues only
python triage.py --mode claims      # recently merged, ready to claim
python triage.py --mode forks       # fork status report
python triage.py --forks            # interactive fork assistant
python triage.py --repo owner/repo  # filter to one repo
python triage.py --json             # raw JSON (pipe-friendly)
python triage.py --include-drafts   # include draft PRs
python triage.py --claims-days 30   # look back 30 days for merged PRs
```

## How PR bucketing works

```
NEEDS_YOU      — Their activity is newer than yours, OR CHANGES_REQUESTED
                 and you haven't pushed a commit since the review.
WAITING_ON_THEM — Your activity is newer than theirs (clean push, no feedback yet).
PROBABLY_FINE  — Latest review is APPROVED, or last comment looks like a sign-off.
```

Review state always overrides comment text. A `CHANGES_REQUESTED` review is only
counted as "needs you" if you haven't pushed a new commit after it — fixing feedback
by pushing, not replying, is properly detected.

## Configuration (`.triage.env`)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_USERNAME` | required | Your GitHub username |
| `GITHUB_TOKEN` | required | Read-only GitHub token (or set via `gh auth`) |
| `TRIAGE_INCLUDE_DRAFTS` | `false` | Include draft PRs |
| `TRIAGE_IGNORE_BOTS` | `true` | Skip bot comments when calculating activity |
| `TRIAGE_IGNORE_REPOS` | — | Comma-separated repos to exclude |
| `TRIAGE_ONLY_REPOS` | — | Comma-separated repos to limit to |
| `TRIAGE_MIN_AGE_HOURS` | `0` | Ignore activity younger than N hours |
| `TRIAGE_WEB_PORT` | `5000` | Port for future web dashboard |

## Project structure

```
github-triage/
├── core.py            # detection logic — returns JSON, no I/O
├── github_client.py   # GraphQL + minimal REST client
├── triage.py          # CLI
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
