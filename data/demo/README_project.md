# CampusConnect Backend Service

CampusConnect is a campus event discovery, ticket reservation, and student engagement API built with FastAPI.

## Tech Stack
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Database**: PostgreSQL 15 (Requires local PostgreSQL instance running on port 5432, configured via POSTGRES_URL)
- **Authentication**: JWT Bearer Tokens
- **Client**: Flutter Mobile App

## Getting Started
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure database:
   Ensure PostgreSQL is running and update `POSTGRES_URL` in `.env`.
3. Run migrations and start API:
   ```bash
   uvicorn main:app --reload
   ```

## Contact
- Project Maintainer: Aman (Backend Lead)
- Supervisor: Rohan (Team Lead)
