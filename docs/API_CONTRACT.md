# TRACE API Contract & Documentation

**Team**: HackTitan  
**Hackathon**: CodePuneThinkers Round 2  
**Tagline**: *"When People Leave, Knowledge Shouldn't."*  
**Base URL**: `http://localhost:8000` (or `VITE_API_URL`)  

This document specifies the exact API contract for TRACE Phase 1. Frontend engineers can use the mock JSON examples below to develop against while the API server is running.

---

## 1. Authentication & Demo Identity Header

In Phase 1, authentication uses a lightweight demo-identity header:

```http
X-Demo-User: usr-meera
```

### Pre-Seeded Demo User Identifiers & Clearances

| User ID | Role Alias | Name | Role | Clearance / Notes |
|---|---|---|---|---|
| `usr-meera` | `admin` | Meera Shah | `admin` | Full clearance (sees public, team, and restricted sources) |
| `usr-priya` | `incoming` | Priya Nair | `incoming` | Sees public and team sources (restricted sources hidden) |
| `usr-rahul` | `departing` | Rahul Verma | `departing` | Sees public and team sources (restricted sources hidden) |
| `usr-ankit` | `team_member`| Ankit Rao | `team_member`| General team member clearance |

> **Note**: Missing or invalid `X-Demo-User` on protected routes returns `HTTP 401 Unauthorized` with `{"detail": "..."}`.

---

## 2. Endpoints Specification

### 2.1 Health Check
- **Method**: `GET`
- **Path**: `/api/health`
- **Auth**: None required
- **Description**: Verifies service status and database connectivity.

#### Example Request
```http
GET /api/health HTTP/1.1
Host: localhost:8000
```

#### Example Response (`200 OK`)
```json
{
  "status": "ok",
  "version": "1.0.0",
  "db": "ok"
}
```

---

### 2.2 Load / Reset Demo Workspace
- **Method**: `POST`
- **Path**: `/api/demo/load`
- **Auth**: Optional / None required
- **Description**: Idempotently seeds the Atlas Workspace, users, memberships, project, and registers all synthetic sources.

#### Example Request
```http
POST /api/demo/load HTTP/1.1
Host: localhost:8000
```

#### Example Response (`200 OK`)
```json
{
  "project_id": "prj-atlas-core",
  "workspace_id": "ws-atlas",
  "sources_registered": 7
}
```

---

### 2.3 Current User Profile
- **Method**: `GET`
- **Path**: `/api/me`
- **Headers**: `X-Demo-User: usr-meera`
- **Description**: Resolves active user profile, assigned workspace, and role.

#### Example Request
```http
GET /api/me HTTP/1.1
Host: localhost:8000
X-Demo-User: usr-meera
```

#### Example Response (`200 OK`)
```json
{
  "id": "usr-meera",
  "name": "Meera Shah",
  "email": "meera.shah@example.com",
  "role": "admin",
  "workspace_id": "ws-atlas",
  "workspace_name": "Atlas Workspace"
}
```

---

### 2.4 List Projects
- **Method**: `GET`
- **Path**: `/api/projects`
- **Headers**: `X-Demo-User: usr-meera`
- **Description**: Lists projects accessible within the current user's workspace.

#### Example Request
```http
GET /api/projects HTTP/1.1
Host: localhost:8000
X-Demo-User: usr-meera
```

#### Example Response (`200 OK`)
```json
[
  {
    "id": "prj-atlas-core",
    "workspace_id": "ws-atlas",
    "name": "Atlas Core Platform",
    "description": "Enterprise context and activity management engine (Synthetic Hackathon Demo).",
    "category": "Platform Infrastructure",
    "team_size": 4,
    "technologies": "Python, FastAPI, SQLite, React, Vite",
    "start_date": "2026-10-01T09:00:00Z",
    "is_synthetic": true,
    "created_at": "2026-11-12T10:00:00Z"
  }
]
```

---

### 2.5 Get Project Detail
- **Method**: `GET`
- **Path**: `/api/projects/{id}`
- **Headers**: `X-Demo-User: usr-meera`
- **Description**: Retrieves single project metadata including synthetic flag.

#### Example Request
```http
GET /api/projects/prj-atlas-core HTTP/1.1
Host: localhost:8000
X-Demo-User: usr-meera
```

#### Example Response (`200 OK`)
```json
{
  "id": "prj-atlas-core",
  "workspace_id": "ws-atlas",
  "name": "Atlas Core Platform",
  "description": "Enterprise context and activity management engine (Synthetic Hackathon Demo).",
  "category": "Platform Infrastructure",
  "team_size": 4,
  "technologies": "Python, FastAPI, SQLite, React, Vite",
  "start_date": "2026-10-01T09:00:00Z",
  "is_synthetic": true,
  "created_at": "2026-11-12T10:00:00Z"
}
```

---

### 2.6 Get Project Members
- **Method**: `GET`
- **Path**: `/api/projects/{id}/members`
- **Headers**: `X-Demo-User: usr-meera`
- **Description**: Returns team members associated with the project's workspace.

#### Example Request
```http
GET /api/projects/prj-atlas-core/members HTTP/1.1
Host: localhost:8000
X-Demo-User: usr-meera
```

#### Example Response (`200 OK`)
```json
[
  {
    "user_id": "usr-meera",
    "name": "Meera Shah",
    "email": "meera.shah@example.com",
    "role": "admin"
  },
  {
    "user_id": "usr-priya",
    "name": "Priya Nair",
    "email": "priya.nair@example.com",
    "role": "incoming"
  },
  {
    "user_id": "usr-rahul",
    "name": "Rahul Verma",
    "email": "rahul.verma@example.com",
    "role": "departing"
  },
  {
    "user_id": "usr-ankit",
    "name": "Ankit Rao",
    "email": "ankit.rao@example.com",
    "role": "team_member"
  }
]
```

---

### 2.7 Get Project Sources (With Role Clearance Filtering)
- **Method**: `GET`
- **Path**: `/api/projects/{id}/sources`
- **Headers**: `X-Demo-User: <user_id>`
- **Description**: Returns registered sources.
  - **Admin View (`usr-meera`)**: Returns all 7 sources including `restricted_internal.md`.
  - **Incoming View (`usr-priya`) / Departing View (`usr-rahul`)**: Automatically excludes `restricted_internal.md` (returns 6 sources).

#### Example Request (Admin View)
```http
GET /api/projects/prj-atlas-core/sources HTTP/1.1
Host: localhost:8000
X-Demo-User: usr-meera
```

#### Example Response (`200 OK`)
```json
[
  {
    "id": "SRC-001",
    "type": "github_commits",
    "filename": "commits.json",
    "status": "registered",
    "clearance_level": "team",
    "source_timestamp": "2026-11-10T11:00:00Z",
    "uploaded_at": "2026-11-12T10:00:00Z"
  },
  {
    "id": "SRC-002",
    "type": "csv",
    "filename": "tasks.csv",
    "status": "registered",
    "clearance_level": "team",
    "source_timestamp": "2026-11-09T10:00:00Z",
    "uploaded_at": "2026-11-12T10:00:00Z"
  },
  {
    "id": "SRC-003",
    "type": "markdown",
    "filename": "meeting_notes.md",
    "status": "registered",
    "clearance_level": "team",
    "source_timestamp": "2026-11-02T10:00:00Z",
    "uploaded_at": "2026-11-12T10:00:00Z"
  },
  {
    "id": "SRC-004",
    "type": "chat_json",
    "filename": "chat.json",
    "status": "registered",
    "clearance_level": "team",
    "source_timestamp": "2026-11-10T17:00:00Z",
    "uploaded_at": "2026-11-12T10:00:00Z"
  },
  {
    "id": "SRC-005",
    "type": "markdown",
    "filename": "docs/architecture.md",
    "status": "registered",
    "clearance_level": "public",
    "source_timestamp": "2026-11-08T10:00:00Z",
    "uploaded_at": "2026-11-12T10:00:00Z"
  },
  {
    "id": "SRC-006",
    "type": "markdown",
    "filename": "docs/api_notes.md",
    "status": "registered",
    "clearance_level": "public",
    "source_timestamp": "2026-11-01T10:00:00Z",
    "uploaded_at": "2026-11-12T10:00:00Z"
  },
  {
    "id": "SRC-007",
    "type": "markdown",
    "filename": "restricted_internal.md",
    "status": "registered",
    "clearance_level": "restricted",
    "source_timestamp": "2026-10-25T10:00:00Z",
    "uploaded_at": "2026-11-12T10:00:00Z"
  }
]
```

---

### 2.8 Get Project Summary
- **Method**: `GET`
- **Path**: `/api/projects/{id}/summary`
- **Headers**: `X-Demo-User: usr-meera`
- **Description**: Returns live counts computed strictly from SQLite database rows. Counts are 0 before extraction and contradiction phases.

#### Example Request
```http
GET /api/projects/prj-atlas-core/summary HTTP/1.1
Host: localhost:8000
X-Demo-User: usr-meera
```

#### Example Response (`200 OK`)
```json
{
  "project_id": "prj-atlas-core",
  "project_name": "Atlas Core Platform",
  "is_synthetic": true,
  "source_count": 7,
  "sources_by_type": {
    "github_commits": 1,
    "csv": 1,
    "markdown": 4,
    "chat_json": 1
  },
  "member_count": 4,
  "claim_count": 0,
  "open_contradiction_count": 0
}
```
