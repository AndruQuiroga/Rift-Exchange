from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from conftest import outcome_id
from rift.api.app import create_app
from rift.auth import create_invite
from rift.config import Settings
from rift.models import Fixture, Market, Outcome

H = {"x-rift-client": "web"}


@pytest.fixture
def api(factory, world):
    with factory() as s, s.begin():
        # Push the fixture into the future relative to the real DB clock used by the API.
        s.execute(update(Fixture).values(scheduled_at=Fixture.scheduled_at + timedelta(days=3650)))
        s.execute(update(Market).values(close_at=Market.close_at + timedelta(days=3650)))
        codes = [create_invite(s) for _ in range(2)]
    app = create_app(Settings(season_code="test"), factory)
    return app, codes


def signup(app, code, handle):
    client = TestClient(app)
    r = client.post("/api/v1/auth/redeem", json={"code": code, "handle": handle}, headers=H)
    assert r.status_code == 200, r.text
    return client


def test_invite_flow_and_csrf(api):
    app, codes = api
    anon = TestClient(app)
    assert anon.get("/api/v1/me").status_code == 401
    assert anon.post("/api/v1/auth/redeem", json={"code": codes[0], "handle": "kai"}).status_code == 403
    kai = signup(app, codes[0], "kai")
    me = kai.get("/api/v1/me").json()
    assert me["wallet"]["available_rc"] >= 1000
    r = TestClient(app).post("/api/v1/auth/redeem", json={"code": codes[0], "handle": "kai2"}, headers=H)
    assert r.json()["error"]["code"] == "INVITE_INVALID"


def test_place_retry_and_privacy(api, factory, world):
    app, codes = api
    kai, mika = signup(app, codes[0], "kai"), signup(app, codes[1], "mika")
    events = kai.get("/api/v1/events").json()["events"]
    assert events[0]["featured"]["outcomes"][0]["odds"] == "1.62"
    atlas = outcome_id(factory, world["market"], "A")
    q = kai.post("/api/v1/quotes", json={"items": [{"outcome_id": str(atlas), "stake_rc": 400}]}, headers=H).json()
    assert q["items"][0]["potential_return_rc"] == 648
    body = {"quote_id": q["quote_id"], "confirm_odds_versions": {str(atlas): 1}}
    r1 = kai.post("/api/v1/tickets", json=body, headers={**H, "Idempotency-Key": "abc"})
    r2 = kai.post("/api/v1/tickets", json=body, headers={**H, "Idempotency-Key": "abc"})
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json()["ticket_id"] == r2.json()["ticket_id"]
    assert kai.get("/api/v1/tickets/by-key/abc").json()["ticket_id"] == r1.json()["ticket_id"]
    assert kai.get("/api/v1/me").json()["wallet"]["open_stake_rc"] == 400
    # Friends can't see an open market's picks...
    assert mika.get("/api/v1/league/activity").json()["activity"] == []
    with factory() as s, s.begin():
        s.execute(update(Market).values(state="LOCKED"))
    # ...until it locks.
    act = mika.get("/api/v1/league/activity").json()["activity"]
    assert act[0]["user"]["handle"] == "kai" and act[0]["stake_rc"] == 400
    standings = mika.get("/api/v1/league/standings").json()["standings"]
    assert {r["user"]["handle"] for r in standings} == {"kai", "mika"}


def test_odds_change_returns_new_quote(api, factory, world):
    app, codes = api
    kai = signup(app, codes[0], "kai")
    atlas = outcome_id(factory, world["market"], "A")
    q = kai.post("/api/v1/quotes", json={"items": [{"outcome_id": str(atlas), "stake_rc": 100}]}, headers=H).json()
    with factory() as s, s.begin():
        s.execute(update(Outcome).where(Outcome.id == atlas).values(odds_version=2, odds=1.70))
    r = kai.post("/api/v1/tickets", json={"quote_id": q["quote_id"], "confirm_odds_versions": {str(atlas): 1}},
                 headers={**H, "Idempotency-Key": "x"})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "ODDS_CHANGED"
    assert err["details"]["new_quote"]["items"][0]["odds"] == "1.70"
    assert err["details"]["previous_items"][0]["odds"] == "1.62"
