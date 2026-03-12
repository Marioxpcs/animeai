"""
db/database.py
SQLAlchemy engine, session factory, and FastAPI dependency.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # reconnect on stale connections
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """
    Create all tables and enable the pgvector extension.
    Safe to run multiple times (CREATE IF NOT EXISTS semantics).
    """
    from db.schema import Base

    # Enable pgvector before creating tables that use the Vector type
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
    print("  ✅  Database tables created (or already exist)")


def get_db():
    """FastAPI dependency — yields a DB session and closes it on exit."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
