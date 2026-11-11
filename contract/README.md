# TRACE API Contract & Schema Specification

This document defines the data models, role clearances, and API endpoints for **TRACE** (Team Records, Activity & Context Engine). It serves as the primary agreement between the backend and the Phase 2 frontend application.

---

## 1. Role Clearances & Access Labels

TRACE uses a strict three-tier hierarchy for both role clearances and data access labels:

$$\text{public} < \text{internal} < \text{restricted}$$

| Role ID | Role Name | Clearance | Allowed Access Labels |
|---|---|---|---|
| `external_reviewer` | External Reviewer | `public` | `public` |
| `incoming_developer` | Incoming Developer | `internal` | `public`, `internal` |
| `team_lead` | Team Lead | `restricted` | `public`, `internal`, `restricted` |

### The Evidence Inheritance Rule (Phase 7 Enforced)
> **Design Rule:** A claim's `access_label` must equal the **strictest** label among its cited evidence sources.
> - If any evidence is from a `restricted` source, the claim is `restricted`.
> - If no evidence is `restricted` but at least one is `internal`, the claim is `internal`.
> - A claim is only `public` if 100% of its evidence sources are `public`.

---

## 2. Core Domain Models

### 2.1 Source
Represents an ingested artifact stream (file, commit log, issue tracker, chat export).

- **Fields**:
  - `id` (`string`, required): Unique identifier (e.g., `"src-git-log"`).
  - `project_id` (`string`, required): Parent project ID.
  - `type` (`string`, required): One of `git`, `pr`, `task`, `note`, `chat`, `doc`.
  - `title` (`string`, required): Descriptive title.
  - `origin_ref` (`string`, required): File path, URL, or external URI.
  - `access_label` (`string`, required): One of `public`, `internal`, `restricted`.
  - `created_at` (`string` or `null`, optional): ISO 8601 timestamp.

```json
{
  "id": "src-git-log",
  "project_id": "proj-campusconnect",
  "type": "git",
  "title": "Git Commit Log",
  "origin_ref": "data/demo/git_log.json",
  "access_label": "internal",
  "created_at": "2026-11-01T10:00:00Z"
}
```

---

### 2.2 ActivityItem
Represents an atomic entry parsed from a Source (Phase 3).

- **Fields**:
  - `id` (`string`, required): Unique item ID.
  - `source_id` (`string`, required): Foreign key to Source.
  - `kind` (`string`, required): E.g., `commit`, `pr_comment`, `task_card`, `chat_message`.
  - `author` (`string` or `null`): Author handle or name.
  - `timestamp` (`string` or `null`): Event timestamp.
  - `text` (`string`, required): Raw message, commit message, or snippet.
  - `ref` (`string` or `null`): Commit SHA, message ID, task key.
  - `access_label` (`string`, required): One of `public`, `internal`, `restricted`.

```json
{
  "id": "act-c1-01",
  "source_id": "src-chat",
  "kind": "chat_message",
  "author": "aman",
  "timestamp": "2026-10-18T14:22:00Z",
  "text": "Switched to SQLite because college server cannot run a background DB service.",
  "ref": "msg-108",
  "access_label": "internal"
}
```

---

### 2.3 Evidence
An explicit citation tying a Claim back to a source artifact and verbatim quote.

- **Fields**:
  - `id` (`string` or `null`): Evidence identifier.
  - `claim_id` (`string` or `null`): Claim identifier.
  - `activity_item_id` (`string` or `null`): Optional reference to an atomic ActivityItem.
  - `source_id` (`string`, required): Source identifier.
  - `source_title` (`string` or `null`): Display title of the source.
  - `quote` (`string`, max 200 chars, required): Exact snippet or quote.
  - `locator` (`string`, required): Commit SHA, PR number, line reference, task ID, or note section.

```json
{
  "id": "ev-01",
  "claim_id": "claim-c1",
  "activity_item_id": null,
  "source_id": "src-prs",
  "source_title": "GitHub Pull Requests",
  "quote": "PR #38: Payment integration is open with 3 unresolved review comments.",
  "locator": "PR #38 comments"
}
```

---

### 2.4 Claim
An assertion or finding derived from project activity with verifiable status and evidence citations.

- **Fields**:
  - `id` (`string`, required): Unique claim ID (e.g., `"claim-c1"`).
  - `project_id` (`string` or `null`): Project ID.
  - `type` (`string`, required): One of `state`, `decision`, `task`, `blocker`, `dependency`, `ownership`, `contradiction`, `open_loop`, `gap`.
  - `statement` (`string`, required): Plain-English factual statement.
  - `status` (`string`, required): One of `verified`, `inferred`, `conflicting`, `missing`.
  - `confidence_note` (`string` or `null`): Rationale or analytical summary.
  - `owner` (`string` or `null`): Primary person responsible or affected.
  - `access_label` (`string`, required): `public`, `internal`, or `restricted`.
  - `review_state` (`string`, required): `pending`, `accepted`, `edited`, or `rejected`.
  - `created_at` (`string` or `null`): Timestamp created.
  - `evidence` (`list[Evidence]`, required): Array of citations (1-2 minimum per claim).

```json
{
  "id": "claim-c1",
  "project_id": "proj-campusconnect",
  "type": "contradiction",
  "statement": "Payment integration task T-12 is marked Done in task tracker, but PR #38 remains open with 3 unresolved comments.",
  "status": "conflicting",
  "confidence_note": "Tracker status does not reflect code review reality in PR #38.",
  "owner": "aman",
  "access_label": "internal",
  "review_state": "pending",
  "created_at": "2026-11-04T12:00:00Z",
  "evidence": [
    {
      "id": "ev-c1-1",
      "claim_id": "claim-c1",
      "activity_item_id": null,
      "source_id": "src-tasks",
      "source_title": "Project Tasks CSV",
      "quote": "T-12, Payment integration, aman, Done, 2026-10-30, #38",
      "locator": "tasks.csv:T-12"
    },
    {
      "id": "ev-c1-2",
      "claim_id": "claim-c1",
      "activity_item_id": null,
      "source_id": "src-prs",
      "source_title": "Pull Requests",
      "quote": "PR #38 state: open, 3 unresolved comments on webhook idempotency",
      "locator": "pull_requests.json:#38"
    }
  ]
}
```

---

### 2.5 GapQuestion
Clarification question generated when key information or rationale is missing.

- **Fields**:
  - `id` (`string`, required): Unique identifier.
  - `claim_id` (`string`, required): The related missing claim.
  - `question` (`string`, required): Inquiry to outgoing team member.
  - `answer` (`string` or `null`): Response if provided.
  - `answered_by` (`string` or `null`): Author of answer.
  - `answered_at` (`string` or `null`): ISO timestamp when answered.

```json
{
  "id": "gq-01",
  "claim_id": "claim-d2",
  "question": "What is the intended invalidation policy and sizing rationale for the newly added in-memory cache layer?",
  "answer": null,
  "answered_by": null,
  "answered_at": null
}
```

---

### 2.6 Review
Audit log of human review decisions made on a claim.

- **Fields**:
  - `id` (`string`, required): Unique review identifier.
  - `claim_id` (`string`, required): Target claim ID.
  - `action` (`string`, required): One of `accept`, `edit`, `reject`.
  - `edited_statement` (`string` or `null`): If edited, the revised text.
  - `reviewer` (`string`, required): Reviewer name or role.
  - `version` (`integer`, required): Review revision number.
  - `created_at` (`string` or `null`): Timestamp of review.

```json
{
  "id": "rev-01",
  "claim_id": "claim-c1",
  "action": "accept",
  "edited_statement": null,
  "reviewer": "rohan",
  "version": 1,
  "created_at": "2026-11-05T09:15:00Z"
}
```

---

### 2.7 Handover
Top-level handover package compiling all claims, statuses, and sign-offs for a project.

- **Fields**:
  - `id` (`string`, required): Handover ID.
  - `project_id` (`string`, required): Project ID.
  - `version` (`integer`, required): Handover version number.
  - `status` (`string`, required): `draft` or `approved`.
  - `approved_by` (`string` or `null`): Approver username/role.
  - `approved_at` (`string` or `null`): Approval timestamp.
  - `acknowledged_by` (`string` or `null`): Incoming developer acknowledgement.
  - `acknowledged_at` (`string` or `null`): Acknowledgement timestamp.
  - `created_at` (`string` or `null`): Creation timestamp.
  - `claims` (`list[Claim]`, required): List of claims included in this handover.

---

### 2.8 RoleView
A filtered view of a Handover adapted for a specific role clearance.

- **Fields**:
  - `role` (`string`, required): Target role ID.
  - `clearance` (`string`, required): Clearance level (`public`, `internal`, `restricted`).
  - `handover` (`Handover`, required): Handover containing only claims allowed by clearance.
  - `hidden_count` (`integer`, required): Number of claims redacted due to clearance restrictions.

```json
{
  "role": "external_reviewer",
  "clearance": "public",
  "handover": { "...": "Filtered claims" },
  "hidden_count": 9
}
```

---

### 2.9 PlanStep
Ranked handover action step indicating next priorities for incoming engineers.

- **Fields**:
  - `id` (`string`, required): Step ID.
  - `handover_id` (`string` or `null`): Handover reference.
  - `rank` (`integer`, required): 1-indexed ordering priority.
  - `action` (`string`, required): Action statement.
  - `reason` (`string`, required): Justification referencing findings.
  - `claim_ids` (`list[string]`, required): Associated claim IDs.

```json
{
  "id": "step-1",
  "handover_id": "ho-campusconnect-01",
  "rank": 1,
  "action": "Resolve PR #38 payment webhook comments and align task T-12 status.",
  "reason": "Prevents deploying untested payment flows to production.",
  "claim_ids": ["claim-c1"]
}
```

---

## 3. API Endpoints

### 3.1 Phase 1 Endpoints (Active)

| Method | Endpoint | Query Params | Description |
|---|---|---|---|
| `GET` | `/health` | none | Returns server health status `{"status": "ok"}` |
| `GET` | `/api/roles` | none | Lists the 3 defined system roles and their clearance |
| `GET` | `/api/demo/sources` | `role` (`string`) | Lists sources accessible by the specified role |
| `GET` | `/api/contract` | none | Returns machine-readable contract specification |

### 3.2 Roadmap Endpoints (Marked Planned)

| Method | Endpoint | Query / Body | Planned Phase | Purpose |
|---|---|---|---|---|
| `POST` | `/api/projects/demo/load` | `{ "reset": true }` | Phase 3 | Ingests and parses demo files into `activity_items`. |
| `POST` | `/api/projects/{id}/analyze` | none | Phase 4 | Runs fact-checking, contradiction detection, and claim generation. |
| `GET` | `/api/handover` | `role=<role>` | Phase 5 | Retrieves role-filtered Handover package. |
| `POST` | `/api/claims/{id}/review` | `{ "action": "...", "edited_statement": "..." }` | Phase 6 | Submits human review on a claim. |
| `POST` | `/api/gap-questions/{id}/answer` | `{ "answer": "..." }` | Phase 6 | Answers an open gap question. |
| `POST` | `/api/handover/approve` | `{ "approved_by": "..." }` | Phase 6 | Team lead approves the handover package. |
| `POST` | `/api/handover/acknowledge` | `{ "acknowledged_by": "..." }` | Phase 6 | Incoming engineer acknowledges receipt. |
| `GET` | `/api/plan` | `role=<role>` | Phase 5 | Retrieves 5 ranked action steps for the handover. |
