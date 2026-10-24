from datetime import timedelta

import pytest
from conftest import T0
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_api import H, api  # noqa: F401 -- shared API fixture

from rift import auth
from rift.models import Season, SignInLink, User


def test_link_reusable_after_cookie_loss_rotation_and_revocation(factory, world):
    with factory() as db, db.begin():
        user = db.get(User, world["alice"])
        token = auth.create_sign_in_link(db, user)
    with factory() as db, db.begin():
        assert db.get(SignInLink, world["alice"]).token_hash == auth.digest(token)
        first_user, first_session = auth.redeem_sign_in_link(db, token, T0, 60)
        later_user, later_session = auth.redeem_sign_in_link(db, token, T0 + timedelta(days=3650), 60)
        assert first_user.id == later_user.id == world["alice"]
        assert first_session != later_session
        replacement = auth.create_sign_in_link(db, first_user)
    with factory() as db, db.begin():
        with pytest.raises(auth.AuthError, match="invalid or has been revoked"):
            auth.redeem_sign_in_link(db, token, T0, 60)
        user, _ = auth.redeem_sign_in_link(db, replacement, T0, 60)
        auth.revoke_sign_in_link(db, user)
    with factory() as db, db.begin():
        assert db.scalars(select(SignInLink)).all() == []
        with pytest.raises(auth.AuthError):
            auth.redeem_sign_in_link(db, replacement, T0, 60)


def test_link_api_csrf_cookie_and_invalid_token(api, factory, world):  # noqa: F811
    app, _ = api
    with factory() as db, db.begin():
        auth.grants.join_season(db, db.get(Season, world["season"]), world["alice"], T0)
        token = auth.create_sign_in_link(db, db.get(User, world["alice"]))
    client = TestClient(app)
    endpoint = "/api/v1/auth/sign-in-link"
    assert client.post(endpoint, json={"token": token}).status_code == 403
    assert client.post(endpoint, json={"token": "x" * 43}, headers=H).status_code == 400
    assert client.post(endpoint, json={"token": ""}, headers=H).status_code == 422
    for _ in range(2):
        client.cookies.clear()
        response = client.post(endpoint, json={"token": token}, headers=H)
        assert response.status_code == 200
        assert response.json()["user"]["handle"] == "alice"
        assert response.headers["cache-control"] == "no-store"
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/api/v1/me").status_code == 200
