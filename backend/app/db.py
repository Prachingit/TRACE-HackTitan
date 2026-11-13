from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings

# Engine setup with SQLite thread compatibility
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()

def init_db() -> None:
    """Initialize database tables."""
    import app.models  # Ensure all models are registered
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency for obtaining database sessions in FastAPI routes."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
