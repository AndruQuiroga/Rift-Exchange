"""Release jobs and worker probe; invoked with python -m rift.operations."""

import argparse
import time
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rift.config import get_settings
from rift.db import db_now, get_engine, session_factory
from rift.models import ProviderSync


def wait_database(attempts: int = 60, interval: float = 2) -> None:
    for attempt in range(attempts):
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except SQLAlchemyError:
            if attempt == attempts - 1:
                raise RuntimeError("Database did not become available") from None
            time.sleep(interval)


def check_worker(max_age_seconds: int = 300) -> None:
    with session_factory()() as session:
        now = db_now(session)
        for job in ("lock", "grants"):
            row = session.get(ProviderSync, job)
            if row is None or row.last_ok_at is None or now - row.last_ok_at > timedelta(seconds=max_age_seconds):
                raise RuntimeError(f"Worker job {job} has no recent success")
            if row.last_error_at and row.last_error_at > row.last_ok_at:
                raise RuntimeError(f"Worker job {job} failed after its last success")


def bootstrap() -> None:
    from rift.adapters.leaguepedia import make_source
    from rift.adapters.lolesports import LolesportsClient
    from rift.worker import Worker

    settings = get_settings()
    Worker(session_factory(), settings, LolesportsClient(settings), make_source(settings)).cycle()
    check_worker()
    with session_factory()() as session:
        for job in ("season", "history", "schedule", "markets"):
            row = session.get(ProviderSync, job)
            if row is None or row.last_ok_at is None or (row.last_error_at and row.last_error_at > row.last_ok_at):
                raise RuntimeError(f"Bootstrap job {job} did not succeed; inspect private admin health")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("wait-db", "bootstrap", "check-worker"))
    args = parser.parse_args()
    if args.operation == "wait-db":
        wait_database()
    elif args.operation == "bootstrap":
        bootstrap()
    else:
        check_worker()


if __name__ == "__main__":
    main()
