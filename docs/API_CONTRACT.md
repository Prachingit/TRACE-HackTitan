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
