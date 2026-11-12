# Antigravity Agent Configuration & Rules: 3riage

## 1. Builder Profile & Identity
* **Identity:** Olumide Lala (Olu) — `@pray_4motivatio` (Twitter) / `@Olalolo22` (GitHub).
* **Engineering Standard:** Systems builder, high velocity, rigorous protocol and toolchain engineer.
* **Mindset:** Pragmatic, direct, high-signal. Values clean mechanism design, fast turnaround, and zero fluff.

---

## 2. Project Architecture & Purpose: 3riage
3riage is a contributor-first triage workstation and CLI engine for high-velocity open-source contributors and bounty hunters.

### The 4 Core Engines:
1. **Ball-in-Court Engine:**
   - Diffs the author's latest commit timestamp against each reviewer's review timestamp.
   - If `Commit TS > Review TS`: Maintainer turn (Pending Review).
   - If `Review TS > Commit TS` and state is `CHANGES_REQUESTED`: Contributor turn (Action Required).
2. **Review Consensus Engine:**
   - Evaluates multi-reviewer state per reviewer.
   - An approval from Maintainer A cannot conceal an unresolved `CHANGES_REQUESTED` block from Maintainer B.
3. **Application Tracker:**
   - Ingests `involves:@me` search queries crossed against open PRs.
   - Detects issues where the contributor applied/commented but hasn't opened a PR yet (active bids vs outbid).
4. **Claimable Bounty Shelf:**
   - Indexes PRs merged within the last 14 days (`MergedAt >= Now - 14 Days`) for reward and payout tracking.

### Sandbox / Mock Dataset:
* `mock_data.py` provides a complete, curated dataset simulating complex contributor situations (deadlocks, unassigned forks, pending reviews, stale PRs).
* When running without live GitHub credentials, use `mock_data.py` to test and develop features offline or on mobile.

---

## 3. Formatting & Engineering Rules (MANDATORY)
* **Rule 1: NO LaTeX Math:** The user's chat UI does NOT render LaTeX math (`$...$` or `$$...$$` renders as broken, raw code). Always write formulas and calculations in plain text or fenced code blocks.
* **Rule 2: Capable Tone:** Olu is an experienced systems engineer. Explain architectural decisions, trade-offs, and code cleanly without superficial padding or patronizing explanations.
* **Rule 3: Test Verification:** Before declaring tasks done, verify functionality using existing tests (`pytest tests/`) or mock data endpoints.
