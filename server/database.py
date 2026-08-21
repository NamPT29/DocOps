import os
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

def get_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Use DATABASE_URL from .env or fallback to default
SQLALCHEMY_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/scan_data",
)

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        # Keep enough headroom for parallel API requests while allowing the
        # values to be tuned without another code change.
        pool_size=int(os.environ.get("DB_POOL_SIZE", "20")),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "30")),
        pool_recycle=int(os.environ.get("DB_POOL_RECYCLE", "1800")),
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
