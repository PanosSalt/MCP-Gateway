from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

Base = declarative_base()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict = {
        "pool_pre_ping": True,   # Discard stale connections before use
        "pool_recycle": 3600,    # Recycle connections after 1 hour (avoids firewall drops)
    }
    if url.startswith("postgresql"):
        # Enforce a 30-second statement timeout on the gateway's own DB to prevent
        # runaway queries from blocking worker threads indefinitely.
        kwargs["connect_args"] = {"options": "-c statement_timeout=30000"}
    return create_engine(url, **kwargs)


@lru_cache(maxsize=1)
def _get_session_factory() -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_session() -> Session:
    return _get_session_factory()()


def get_db() -> Generator[Session, None, None]:
    db = get_session()
    try:
        yield db
    finally:
        db.close()
