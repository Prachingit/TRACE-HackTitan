"""FastAPI application for TRACE — Phase 2.

Team HackTitan - CodePuneThinkers Hackathon Round 2.
Tagline: 'When People Leave, Knowledge Shouldn't.'
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.db import SessionLocal
from app.routers import analysis, assistant, auth, contradictions, handovers, health, interview, projects, review, sources, workspaces
from app.routers.auth import limiter
from app.services.background import reset_stuck_sources

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply Alembic migrations (never drop/recreate tables)
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    command.upgrade(cfg, "head")

    # Reset any sources stuck in 'parsing' from a previous crash & seed synthetic demo workspace
    db = SessionLocal()
    try:
        count = reset_stuck_sources(db)
        if count:
            print(f"[TRACE Startup] Reset {count} stuck source(s) to 'queued'.")
        from app.services.demo import ensure_demo_seeded
        ensure_demo_seeded(db)
    except Exception as exc:
        print(f"[TRACE Startup] Demo seed skipped: {exc}")
    finally:
        db.close()

    yield


app = FastAPI(
    title="TRACE API",
    description="Team Records, Activity & Context Engine API (Team HackTitan)",
    version="2.0.0",
    lifespan=lifespan,
)

# Rate-limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_request: Request, _exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response

# CORS (dev only — in production, frontend is served from same origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(projects.router)
app.include_router(sources.router)
app.include_router(analysis.router)
app.include_router(contradictions.router)
app.include_router(interview.router)
app.include_router(review.router)
app.include_router(handovers.router)
app.include_router(assistant.router)

# Serve built React frontend (single-origin deploy)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="API route not found.")
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"detail": "Frontend not built yet."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=(settings.ENV == "development"),
    )


