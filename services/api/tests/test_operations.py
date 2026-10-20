from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from rift.api.app import create_app
from rift.config import Settings
from rift.db import db_now
from rift.models import ProviderSync
from rift.operations import check_worker


def test_secret_file_overrides_environment(tmp_path, monkeypatch):
    path = tmp_path / "url"
    path.write_text("postgresql+psycopg://secret@db/rift\n")
    monkeypatch.setenv("RIFT_DATABASE_URL", "postgresql+psycopg://wrong@localhost/rift")
    monkeypatch.setenv("RIFT_DATABASE_URL_FILE", str(path))
    assert Settings().database_url == "postgresql+psycopg://secret@db/rift"
    path.write_text("")
    with pytest.raises(ValueError, match="Empty configured secret"):
        Settings()
    path.unlink()
    with pytest.raises(ValueError, match="Cannot read configured secret"):
        Settings()


def test_readiness_requires_migration_and_season(factory, world):
    app = create_app(Settings(season_code="test"), factory)
    with factory() as session, session.begin():
        session.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) PRIMARY KEY)"))
    client = TestClient(app)
    assert client.get("/api/v1/healthz").status_code == 200
    assert client.get("/api/v1/health/ready").status_code == 503
    with factory() as session, session.begin():
        session.execute(text("INSERT INTO alembic_version VALUES ('test')"))
    assert client.get("/api/v1/health/ready").status_code == 200
    other = TestClient(create_app(Settings(season_code="missing"), factory))
    assert other.get("/api/v1/health/ready").status_code == 503
    with factory() as session, session.begin():
        session.execute(text("DELETE FROM alembic_version"))


def test_readiness_hides_database_failure():
    def unavailable():
        from sqlalchemy.exc import OperationalError
        raise OperationalError("sensitive SQL", {}, Exception("private connection string"))

    response = TestClient(create_app(Settings(), unavailable)).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"ok": False}


def test_worker_probe_rejects_stale_and_failed_jobs(factory, monkeypatch):
    monkeypatch.setattr("rift.operations.session_factory", lambda: factory)
    with pytest.raises(RuntimeError, match="no recent success"):
        check_worker()
    with factory() as session, session.begin():
        now = db_now(session)
        session.add_all([ProviderSync(job=job, last_ok_at=now) for job in ("lock", "grants")])
    check_worker()
    with factory() as session, session.begin():
        session.get(ProviderSync, "lock").last_ok_at = now - timedelta(minutes=10)
    with pytest.raises(RuntimeError, match="no recent success"):
        check_worker()
    with factory() as session, session.begin():
        row = session.get(ProviderSync, "lock")
        row.last_ok_at = now
        row.last_error_at = now + timedelta(seconds=1)
    with pytest.raises(RuntimeError, match="failed after"):
        check_worker()
