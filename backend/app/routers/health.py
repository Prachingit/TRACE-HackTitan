"""Health check endpoint."""

from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings
from app.db import get_db
from app.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health(db: Session = Depends(get_db)):
    """Return system, database, and storage health status."""
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    storage_status = "ok"
    try:
        data_dir = Path(settings.DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception:
        storage_status = "error"

    overall = "ok" if (db_status == "ok" and storage_status == "ok") else "degraded"
    return HealthResponse(
        status=overall,
        version="2.0.0",
        db=db_status,
        storage=storage_status,
    )
