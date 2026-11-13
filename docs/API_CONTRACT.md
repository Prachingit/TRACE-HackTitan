# TRACE API contract (Phase 2)

Base path `/api`. Auth is an httpOnly cookie `trace_session` (SameSite=Lax, Secure when `ENV=production`). Errors use `{"detail": "message"}`. Unknown or cross-workspace resources return **404**, never 403, so existence is not leaked. Phase 1's `X-Demo-User` header and `/api/demo/*` endpoints no longer exist.

Clearance levels: `public`, `team`, `restricted`. Roles: `admin`, `team_member`, `incoming`, `departing`. `incoming` and `departing` never see restricted sources, in lists, details, or chunks.

## Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/signup` | `{name,email,password,confirm_password}`. Password min 10 chars. 409 if email exists (case-insensitive). Sets cookie. Rate limit 5/min. |
| POST | `/auth/login` | `{email,password}`. Generic 401 "Invalid email or password." Rate limit 10/min. |
| POST | `/auth/logout` | 204. Clears cookie. |
| GET | `/auth/me` | Current user, 401 if no session. |
| POST | `/auth/forgot-password` | 202. Returns an honest "not configured" message unless all four SMTP vars are set. No reset email is sent in this phase. |

## Workspaces
| Method | Path | Notes |
|---|---|---|
| POST | `/workspaces` | `{name}`. Caller becomes admin. |
| GET | `/workspaces` | Caller's workspaces with their `role`. |
| GET | `/workspaces/{id}` | 404 if not a member. |
| GET | `/workspaces/{id}/members` | Any member. |
| PATCH | `/workspaces/{id}/members/{user_id}/role` | Admin. Cannot demote last admin. |
| DELETE | `/workspaces/{id}/members/{user_id}` | Admin. Cannot remove self. 204. |
| POST | `/workspaces/{id}/invites` | Admin. `{role, expires_hours=48}`. Single-use token. |
| GET | `/workspaces/{id}/invites` | Admin. |
| DELETE | `/workspaces/{id}/invites/{invite_id}` | Admin. Revokes. 204. |
| GET | `/workspaces/invite-preview/{token}` | No auth. Workspace name and role. |
| POST | `/workspaces/join` | `{token}`. 410 if revoked, used or expired. 409 if already a member. |

## Projects
| Method | Path | Notes |
|---|---|---|
| GET | `/projects` | All projects in caller's workspaces. |
| POST | `/projects` | Admin. `{workspace_id,name,description,category,team_size,technologies,start_date}`. |
| GET / PATCH / DELETE | `/projects/{id}` | PATCH and DELETE admin only. |
| GET | `/projects/{id}/members` | Workspace members. |
| GET | `/projects/{id}/summary` | `source_count, sources_by_type, chunk_count, member_count, claim_count, open_contradiction_count`. All computed from rows. |

## Sources
`status`: `queued` -> `parsing` -> `parsed` or `failed` (`error_message` set on failure). Source IDs look like `SRC-1A2B3C4D` and are globally unique.

| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/sources` | Clearance-filtered. Includes `chunk_count`. |
| GET | `/projects/{id}/sources/{sid}` | |
| GET | `/projects/{id}/sources/{sid}/chunks?limit&offset` | Limit max 200. |
| POST | `/projects/{id}/sources/upload` | multipart: `file`, `clearance_level`. Types: pdf, docx, txt, md, csv, json. 400 bad type, spoofed content or empty. 409 duplicate content hash. 413 over 15 MB. Max 50 sources per project. Only admins may set `restricted` (403). |
| POST | `/projects/{id}/sources/github` | `{repo_url, clearance_level, fetch_commits, fetch_prs, fetch_issues}`. Public repos. Up to 200 commits. `GITHUB_TOKEN` optional. |
| POST | `/projects/{id}/sources/manual` | `{title, content, clearance_level, author?}`. Parsed immediately. |
| POST | `/projects/{id}/sources/{sid}/retry` | Only for `failed` or `queued`. |
| DELETE | `/projects/{id}/sources/{sid}` | Admin. Removes chunks and stored file. 204. |
| POST | `/projects/{id}/sample` | Admin. Loads the synthetic Atlas files into this project only and marks it `is_synthetic`. Idempotent by content hash. |

## Chunk locators
Markdown/TXT `L12-L20`; PDF `page:3`; DOCX `para:4-7` or `table:1:row:2`; CSV `row:5`; chat/generic JSON `idx:n`; commit JSON and GitHub `sha:...`, `pr:N`, `issue:N`; manual `manual`.

## Reconstruction & Analysis (Phase 3)
`Run` tracks 5 stages: `reading_sources`, `extracting`, `correlating`, `detecting_gaps`, `preparing`.
Claims carry `id` (`CLM-...`), `claim_type` (`task_status`, `decision`, `ownership`, `blocker`, `dependency`, `contribution`, `testing`, `doc_gap`), `verification_status` (`verified`, `inferred`, `missing`, `conflicting`), `review_status` (`unreviewed`, `approved`, `edited`, `rejected`), `extractor` (`rule` or `llm`), `origin_label` (`human-reviewed`, `ai-extracted`, `rule-extracted`), and `clearance_level` (`public`, `team`, `restricted`).

| Method | Path | Notes |
|---|---|---|
| POST | `/projects/{id}/analyze` | 202. Starts background analysis run on parsed sources. Preserves human-reviewed claims and existing contradiction resolutions. |
| GET | `/projects/{id}/runs/latest` | Latest `Run` with stages and summary counts, or `null` if never analysed. |
| GET | `/projects/{id}/timeline` | Chronological events across clearance-visible sources. (Also `GET /timeline?project_id=...`). |
| GET | `/projects/{id}/modules` | Correlated modules with claim counts and owners. (Also `GET /modules?project_id=...`). |
| POST | `/projects/{id}/modules/rename` | `{from_module, to_module}`. Saves alias and updates claims. |

## Evidence Ledger & Citation Validation (Phase 4)
| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/claims` | Filters: `type`, `module`, `status`, `owner`, `review_status`, `q`. Clearance-filtered. (Also `GET /claims?project_id=...`). |
| GET | `/claims/{claim_id}` | Full claim detail + `evidence[]` with `chunk_text`, `excerpt`, `highlight_start`, `highlight_end`. 404 if restricted for `incoming`/`departing` or cross-workspace. |
| PATCH | `/claims/{claim_id}/review` | `{review_status, title?, text?, owner_name?, module?}`. Sets `origin_label` to `human-reviewed`. |
| GET | `/projects/{id}/ledger/validation` | Verifies every `ClaimEvidence.excerpt` exists in `Chunk.text`. Downgrades `verified` claims with 0 valid citations to `missing`. |

## Contradiction Radar (Phase 5)
8 deterministic rules: `STATUS_WITHOUT_EVIDENCE`, `CONFLICTING_STATUS`, `CONFLICTING_OWNERSHIP`, `UNRESOLVED_DEPENDENCY`, `STALE_ACTIVITY`, `UNDOCUMENTED_WORK`, `UNASSIGNED_RESPONSIBILITY`, `MISSING_TEST_EVIDENCE`.
Contradictions carry `clearance_level` (`restricted` hidden from `incoming`/`departing`). Re-running analysis never auto-resolves contradictions.

| Method | Path | Notes |
|---|---|---|
| GET | `/projects/{id}/contradictions` | Filters: `rule_code`, `status`, `severity`. Sorted open-first, then high -> medium -> low. Clearance-filtered. |
| GET | `/contradictions/{contradiction_id}` | Detail including `conflicting_sources[]` and full involved `claims[]` with highlighted evidence. 404 if restricted/cross-workspace. |
| POST | `/contradictions/{contradiction_id}/resolve` | `{note}`. Requires non-empty note (400 otherwise). Marks `status="resolved"` with `resolved_by`, `resolved_at`, `resolution_note`. Does not silently flip claims to `verified`. |
