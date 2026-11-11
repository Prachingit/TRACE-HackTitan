# Planted Test Cases for TRACE Demo Dataset

This document lists all test cases deliberately planted in `data/demo/` for downstream phases (ingestion, contradiction detection, gap generation, access clearance enforcement, and handover generation).

---

## 1. Summary Matrix

| ID | Category | Planted Phenomenon | Exact Files & Locators | Expected Status | Access Label |
|---|---|---|---|---|---|
| **C1** | Contradiction | Task T-12 marked Done vs PR #38 open with 3 unresolved review comments | `tasks.csv:T-12`, `pull_requests.json:#38` | `conflicting` | `internal` |
| **C2** | Contradiction | Task T-15 assigned to Meera (To Do) vs Aman authoring all commits on branch `feature/reminders` | `tasks.csv:T-15`, `git_log.json:branch=feature/reminders` (commits `d1e2f3a`, `e2f3a4b`, `f3a4b5c`) | `conflicting` | `internal` |
| **C3** | Contradiction | README claims PostgreSQL vs code/commits/chat showing SQLite | `README_project.md:Line 7`, `chat.json:msg-14`, `git_log.json:a1b2c3d` | `conflicting` | `internal` |
| **G1** | Undocumented Work | 14 commits on branch `aman/notif-wip` over 3 weeks with 0 task/meeting note mentions | `git_log.json:branch=aman/notif-wip` (commits `1001a01` to `1014a14`), absence in `tasks.csv` & `notes/*` | `missing` | `internal` |
| **D1** | Chat-only Decision | Switch to SQLite rationalized only in chat ("college server can't run a database service") | `chat.json:msg-14`, absence in PRs & meeting notes | `inferred` | `internal` |
| **D2** | Missing Rationale | Commit introducing in-memory cache layer has no rationale recorded anywhere | `git_log.json:c94a2b1`, absence in chat/PRs/notes | `missing` | `internal` |
| **O1** | Open Loop | Chat message promises to confirm vendor API quota with zero follow-up | `chat.json:msg-28` ("will confirm the vendor API quota..."), no subsequent msg | `inferred` | `internal` |
| **R1** | Restricted Source | Confidential vendor pricing and budget notes | `restricted/vendor_budget_notes.md` | `verified` | `restricted` |

---

## 2. Detailed Breakdown

### C1: Payment Integration Status Mismatch
- **Files**:
  - `data/demo/tasks.csv`: Row `T-12,Payment integration,aman,Done,2026-10-30,#38`
  - `data/demo/pull_requests.json`: PR `#38` has `state: "open"` and 3 unresolved comments from Rohan and Meera regarding webhook signature checks and idempotency.
- **Why it matters**: A new engineer relying solely on Jira/tasks would assume payments are shipped and done, while in reality the PR is blocked on security/reliability issues.

### C2: Ownership Mismatch on Event Reminders
- **Files**:
  - `data/demo/tasks.csv`: Row `T-15,Event reminders,meera,To Do,2026-10-28,`
  - `data/demo/git_log.json`: Commits `d1e2f3a`, `e2f3a4b`, `f3a4b5c` authored by `aman` on branch `feature/reminders` explicitly referencing `T-15`.
- **Why it matters**: Task board says Meera has not started, but Aman has implemented half the feature on an unmerged branch.

### C3: Outdated Architecture Documentation
- **Files**:
  - `data/demo/README_project.md`: Lists `Database: PostgreSQL 15`.
  - `data/demo/chat.json`: `msg-14` by Aman ("switched ... to SQLite because college server can't run a database service").
  - `data/demo/git_log.json`: Commit `a1b2c3d` and models configured for SQLite.
- **Why it matters**: Onboarding developers will waste hours attempting to configure PostgreSQL unless corrected.

### G1: Undocumented 14-Commit Feature Branch
- **Files**:
  - `data/demo/git_log.json`: 14 commits on branch `aman/notif-wip` between Oct 14 and Nov 04 (`1001a01` through `1014a14`).
  - `data/demo/tasks.csv`: Only T-11 exists (assigned to Neha as To Do); no task tracks Aman's existing 14 commits.
  - `data/demo/notes/*`: None of the standup or sprint notes mention this work.
- **Why it matters**: 3 weeks of work by the outgoing developer risks being discarded or duplicated by the incoming developer.

### D1: Decision Rationale Hidden in Chat
- **Files**:
  - `data/demo/chat.json`: `msg-14` contains: *"FYI switched the local and staging DB to SQLite because college server can't run a database service."*
  - Not documented in any PR description, architecture doc, or meeting note.
- **Why it matters**: If chat history is lost or not indexed, team members will not understand why SQLite was chosen over PostgreSQL.

### D2: Missing Rationale for In-Memory Caching
- **Files**:
  - `data/demo/git_log.json`: Commit `c94a2b1` ("perf: add in-memory TTLCache to event lookup endpoint").
  - Absence in all PR descriptions, chat channels, and notes.
- **Why it matters**: No sizing limits, invalidation strategies, or justification are recorded.

### O1: Unresolved Vendor API Quota Check
- **Files**:
  - `data/demo/chat.json`: `msg-28` by Aman: *"I will confirm the vendor API quota with the SMS gateway before we wire up ticket SMS alerts."*
  - No subsequent messages or tasks address this confirmation.
- **Why it matters**: Production alert volumes might exceed quota without warning.

### R1: Restricted Budget Document
- **Files**:
  - `data/demo/restricted/vendor_budget_notes.md`
- **Why it matters**: Must strictly be tagged with `access_label = "restricted"`. Visible only to `team_lead` (clearance `restricted`), completely hidden from `incoming_developer` and `external_reviewer`.

---

## 3. Normal / Uncontroversial Items
- `git_log.json`: Standard feature commits on `main` for JWT auth (`c3d4e5f`) and event pagination (`f6a7b8c`).
- `pull_requests.json`: PR `#35`, PR `#36`, PR `#37` are cleanly approved and merged with all comments resolved.
- `tasks.csv`: Tasks `T-01`, `T-02`, `T-03` completed normally and linked to merged PRs.
