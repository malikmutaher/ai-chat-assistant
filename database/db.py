"""
DB engine/session setup.

Usage in FastAPI routes:

    from database.db import get_db

    @router.post("/something")
    def handler(db: Session = Depends(get_db)):
        ...

`init_db()` is called once at app startup (see main.py) to create tables
if they don't exist yet.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import settings
from database.models import Base

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    # Needed for SQLite when accessed from multiple threads (FastAPI's
    # default threadpool for sync endpoints).
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Creates all tables defined in database/models.py if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a session and guarantees it's closed."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
