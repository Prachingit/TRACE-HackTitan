"""FastAPI application for TRACE.

Team HackTitan - CodePuneThinkers Hackathon Round 2.
Tagline: 'When People Leave, Knowledge Shouldn't.'
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Project
from app.routers import demo, health, projects
from app.services.seed import seed_atlas


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize DB tables
    init_db()

    # 2. Deploy-readiness: auto-seed demo dataset on first start if DB is empty
    if settings.AUTO_SEED_ON_STARTUP:
        db = SessionLocal()
        try:
            if db.query(Project).count() == 0:
                print("[TRACE Startup] Database empty. Auto-seeding Atlas Workspace...")
                seed_atlas(db=db)
                print("[TRACE Startup] Auto-seed complete.")
        finally:
            db.close()

    yield


app = FastAPI(
    title="TRACE API",
    description="Team Records, Activity & Context Engine API (Team HackTitan)",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(demo.router)
app.include_router(projects.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=(settings.ENV == "development"),
    )
