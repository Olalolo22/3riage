# Project Dossier: 3riage (Contributor-First GitHub Triage Engine)

**Dossier Generation Date:** November 10, 2026  
**Investigator:** Antigravity Engineering Portfolio Intelligence Analyst  
**Repository Source:** Remote GitHub (`Olalolo22/3riage`) / Local Workspace (`/home/lala_02/3riage`)  
**Access Level:** Public / Open Source  
**Latest Verified Commit:** `58b3d66` (`feat(sandbox): add curated mock dataset and sandbox demo mode (Phase 1)`)  
**Evidence Standard:** E2 (Complete Python Codebase, CLI Interface, Curated Sandbox Engine)

---

## A. Identity and Purpose

- **Project Name:** 3riage
- **Repository URL:** [`https://github.com/Olalolo22/3riage`](https://github.com/Olalolo22/3riage)
- **Relevant Branches:** `4public`, `main`
- **What It Does:** A contributor-first triage engine and command-line workstation for high-velocity open-source contributors and bounty hunters. Surfaces relational GitHub state that native GitHub notifications conceal: PRs where the ball is in your court, issues applied to with no open PR, unforked assigned repositories, and recently merged PRs ready to claim for rewards.
- **Specific Problem Addressed:** High-velocity open-source builders juggling 10+ active repositories miss critical deadlines because GitHub's notification inbox is flat and un-relational. A `Changes Requested` badge stays forever even after a contributor pushes fixes; single approvals mask blocking reviews from other maintainers; and merged PRs drift out of memory before bounties are claimed.
- **Target Audience:** Open-source maintainers, bounty hunters, developer fellows, protocol contributors.

---

## B. Implementation Status

- **Classification:** **Fully Implemented CLI Workstation with Curated Sandbox Mode**
- **Verified Components:**
  - [x] **Relational Contributor Analyzer:** Crosses `involves:@me` search queries against open PRs, identifying issues where the user applied but hasn't submitted code.
  - [x] **"Ball-in-Your-Court" Timestamp Diffing:** Compares the timestamp of the author's latest commit against each reviewer's review timestamp to determine whether the maintainer or the author owes the next move.
  - [x] **Multi-Reviewer Deadlock Resolver:** Evaluates review states per reviewer, preventing an approval from maintainer A from concealing an unresolved request-changes block from maintainer B.
  - [x] **Unforked Repo Detector:** Diffs assigned repositories against user forks.
  - [x] **"Ready to Claim" Bounty Shelf:** Indexes merged PRs from the past 14 days for payout verification.
  - [x] **Phase 1 Sandbox Engine:** Curated mock dataset enabling zero-credential demonstration.

---

## C. Technical Architecture

```
[ GitHub API / GraphQL Gateway ]
                │
                │ Ingests User PRs, Reviews, Issues, and Assigned Repos
                ▼
+--------------------------------------------------------------------------------+
|                        3RIAGE RELATIONAL ANALYSIS PIPELINE                     |
+--------------------------------------------------------------------------------+
|                                                                                |
|  1. Ball-in-Court Engine:                                                      |
|     - For each open PR: Latest Commit TS vs Reviewer Review TS                 |
|     - If Commit TS > Review TS -> Maintainer Turn (Pending Review)             |
|     - If Review TS > Commit TS & State == CHANGES_REQUESTED -> Author Turn     |
|                                                                                |
|  2. Review Consensus Engine:                                                   |
|     - Aggregates latest state per reviewer: approvals cannot mask blocks       |
|                                                                                |
|  3. Application Tracker:                                                       |
|     - Issue Comment Involves:@me AND No Linked PR -> Active Bid                |
|     - Closed / Assigned to Other -> Outbid Alert                               |
|                                                                                |
|  4. Claimable Bounty Shelf:                                                    |
|     - State == MERGED AND MergedAt >= (Now - 14 Days)                          |
+--------------------------------------------------------------------------------+
                │
                ▼
[ Rich Terminal Dashboard (Terminal UI / Markdown Output) ]
```

---

## D. Verification Evidence & Claims

| Claim ID | Claim Description | Evidence Source | Confidence |
| :--- | :--- | :--- | :---: |
| `CLM-3RIAGE-001` | Built contributor triage engine in Python diffing commit vs review timestamps to detect true turnaround bottlenecks. | `triage.py`, commit `58b3d66` | **E2** |
| `CLM-3RIAGE-002` | Implemented multi-reviewer deadlock resolution and 14-day merged PR bounty claim shelf. | `README.md`, `triage/analyzer.py` | **E2** |

---

## E. Interview-Ready Talking Points

- **One-Sentence Pitch:**  
  *"3riage is a contributor-first triage workstation in Python that analyzes relational GitHub state—diffing commit timestamps against reviewer reviews to pinpoint whose turn it is, catching multi-reviewer deadlocks, and surfacing merged PRs ready for bounty payouts."*
