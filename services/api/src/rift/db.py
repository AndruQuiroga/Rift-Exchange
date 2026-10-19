from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from rift.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    with (factory or session_factory())() as session, session.begin():
        yield session


def db_now(session: Session) -> datetime:
    """Authoritative server time: the database clock at statement execution."""
    return session.execute(select(func.clock_timestamp())).scalar_one()
