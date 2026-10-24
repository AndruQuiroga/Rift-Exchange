from datetime import timedelta

import pytest
from conftest import T0, make_market, outcome_id
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from test_timeline import CHAMPS

from rift.api.app import create_app
from rift.auth import create_invite
from rift.config import Settings
from rift.models import Fixture, Game, Market, OutboxEvent, Outcome, Season, SignInCode

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


def test_one_name_makes_the_account(api):
    app, codes = api
    client = TestClient(app)
    r = client.post("/api/v1/auth/redeem", json={"code": codes[0], "name": "  Alice   W "}, headers=H)
    assert r.status_code == 200, r.text
    # "alice" is already the world fixture's handle, so the internal handle gets a suffix.
    assert r.json()["user"] == {**r.json()["user"], "handle": "alice_w", "display_name": "Alice W"}
    r = TestClient(app).post("/api/v1/auth/redeem", json={"code": codes[1], "name": "alice w"}, headers=H)
    assert r.json()["error"]["code"] == "NAME_TAKEN"
    r = TestClient(app).post("/api/v1/auth/redeem", json={"code": codes[1], "name": "A"}, headers=H)
    assert r.json()["error"]["code"] == "NAME_INVALID"


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
    event_id = events[0]["id"]
    hidden = mika.get(f"/api/v1/events/{event_id}/league").json()
    assert hidden["picks"] == []
    # ...only that kai has one, and when it reveals: no side, stake or market.
    assert [(r["user"]["handle"], r["picks"]) for r in hidden["pending"]] == [("kai", 1)]
    assert set(hidden["pending"][0]) == {"user", "picks", "reveals_at"}
    assert kai.get(f"/api/v1/events/{event_id}/league").json()["pending"] == []  # never your own
    with factory() as s, s.begin():
        s.execute(update(Market).values(state="LOCKED"))
    # ...until it locks.
    act = mika.get("/api/v1/league/activity").json()["activity"]
    assert act[0]["user"]["handle"] == "kai" and act[0]["stake_rc"] == 400
    on_match = mika.get(f"/api/v1/events/{event_id}/league").json()["picks"]
    assert [p["user"]["handle"] for p in on_match] == ["kai"]
    assert mika.get(f"/api/v1/events/{event_id}/league").json()["pending"] == []
    assert kai.get(f"/api/v1/events/{event_id}/league").json()["picks"] == []  # never your own
    standings = mika.get("/api/v1/league/standings").json()["standings"]
    assert {r["user"]["handle"] for r in standings} == {"kai", "mika"}
    # Ranked by bankroll: the 400 kai has in play still counts, so placing a bet never drops you down the table.
    kai_row = next(r for r in standings if r["user"]["handle"] == "kai")
    assert kai_row["open_stake_rc"] == 400 and kai_row["bankroll_rc"] == kai_row["available_rc"] + 400
    assert [r["rank"] for r in standings] == [1, 1]  # same grants, nothing settled
    assert {(r["won"], r["lost"], r["won_today"], r["lost_today"], r["today_rank"]) for r in standings} == {(0, 0, 0, 0, 1)}


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


def _pick(client, outcome, stake, key):
    q = client.post("/api/v1/quotes", json={"items": [{"outcome_id": str(outcome), "stake_rc": stake}]},
                    headers=H).json()
    r = client.post("/api/v1/tickets", json={"quote_id": q["quote_id"], "confirm_odds_versions": {str(outcome): 1}},
                    headers={**H, "Idempotency-Key": key})
    assert r.status_code == 201, r.text


def test_event_games_and_live_scoreboard(api, factory, world):
    """Mid-series: Atlas (A) won Game 1 on blue; Game 2 is live with Atlas on red."""
    app, codes = api
    kai, mika = signup(app, codes[0], "kai"), signup(app, codes[1], "mika")
    with factory() as s, s.begin():
        season, fixture = s.get(Season, world["season"]), s.get(Fixture, world["fixture"])
        kills = make_market(s, season, fixture, "total_kills_game", [("OVER", "Over 27.5", "1.90"),
                                                                     ("UNDER", "Under 27.5", "2.10")],
                            params={"game_index": 2, "line": "27.5"}, scope="GAME")
        kills_id = kills.id
    _pick(kai, outcome_id(factory, world["market"], "A"), 100, "k1")
    _pick(kai, outcome_id(factory, kills_id, "OVER"), 50, "k2")

    a, b = world["team_a"], world["team_b"]
    with factory() as s, s.begin():
        fixture = s.get(Fixture, world["fixture"])
        fixture.status, fixture.team_a_wins = "LIVE", 1
        start = fixture.scheduled_at
        s.execute(update(Market).values(state="LOCKED"))
        s.add(Game(fixture_id=fixture.id, provider_id="g1", game_index=1, state="completed", blue_team_id=a,
                   red_team_id=b, winner_team_id=a, started_at=start, ended_at=start + timedelta(minutes=31),
                   stats_complete=True, stats={"players": [{"champion": c, "kills": 1} for c in CHAMPS]}))
        s.add(Game(fixture_id=fixture.id, provider_id="g2", game_index=2, state="inProgress", blue_team_id=b,
                   red_team_id=a, started_at=start + timedelta(minutes=50), timeline={
                       "participants": {"1": {"side": "blue", "champion": "Rumble"}},
                       "live": {"at": "2026-10-23T18:02:34+00:00", "state": "in_game", "clock_s": 754,
                                "kills": {"blue": 3, "red": 5}, "gold": {"blue": 20000, "red": 21000},
                                "towers": {"blue": 1, "red": 0}, "inhibitors": {"blue": 0, "red": 0},
                                "barons": {"blue": 0, "red": 0}, "dragons": {"blue": ["ocean"], "red": []}},
                       "firsts": {"blood": {"side": "red", "team_id": str(a), "at_s": 200},
                                  "tower": {"side": "blue", "team_id": str(b), "at_s": 600}},
                       "dragons": [{"side": "blue", "team_id": str(b), "type": "ocean", "at_s": 400}],
                       "barons": []}))

    detail = kai.get(f"/api/v1/events/{world['fixture']}").json()
    assert [g["window"] for g in detail["games"]] == ["DONE", "LOCKED", "UPCOMING"]
    g1, g2, g3 = detail["games"]
    assert g1["winner"] == "A" and g1["burned_champions"] == [] and g1["ended_at"] is not None
    assert g2["burned_champions"] == CHAMPS and g2["state"] == "inProgress" and g2["winner"] is None
    assert g3 == {"index": 3, "state": "unstarted", "started_at": None, "ended_at": None, "winner": None,
                  "window": "UPCOMING", "opens_when": "When Game 2 ends", "closes_at": None, "early": "UPCOMING",
                  "burned_champions": CHAMPS + ["Rumble"], "lanes": "UPCOMING"}
    assert detail["markets"]  # existing fields stay

    live = kai.get(f"/api/v1/events/{world['fixture']}/live").json()
    assert {k: live[k] for k in ("status", "game_index", "game_clock_s", "gold", "kills", "towers", "dragons")} == {
        "status": "LIVE", "game_index": 2, "game_clock_s": 754, "gold": [21000, 20000], "kills": [5, 3],
        "towers": [0, 1], "dragons": [[], ["ocean"]]}
    assert live["events"] == [
        {"type": "first_blood", "team": "A", "at_s": 200, "detail": None},
        {"type": "dragon", "team": "B", "at_s": 400, "detail": "ocean"},
        {"type": "first_tower", "team": "B", "at_s": 600, "detail": None}]
    picks = {p["market_title"]: p for p in live["my_picks"]}
    assert picks["series_winner"]["live"] == {"score": [1, 0]} and picks["series_winner"]["stake_rc"] == 100
    assert picks["total_kills_game"]["live"] == {"current": 8, "line": "27.5", "needed": 20}
    assert mika.get(f"/api/v1/events/{world['fixture']}/live").json()["my_picks"] == []
    assert TestClient(app).get(f"/api/v1/events/{world['fixture']}/live").status_code == 401


def test_sign_in_code_adds_a_device(api, factory):
    app, codes = api
    phone = signup(app, codes[0], "kai")
    assert TestClient(app).post("/api/v1/auth/sign-in-codes", headers=H).status_code == 401
    first = phone.post("/api/v1/auth/sign-in-codes", headers=H).json()["code"]
    code = phone.post("/api/v1/auth/sign-in-codes", headers=H).json()["code"]
    assert len(code) == 9 and code[4] == "-"
    desktop = TestClient(app)
    # A new code replaces the old one; codes forgive case, spaces and a missing dash.
    r = desktop.post("/api/v1/auth/sign-in", json={"code": first}, headers=H)
    assert r.json()["error"]["code"] == "CODE_INVALID"
    assert desktop.post("/api/v1/auth/sign-in", json={"code": code.replace("-", " ").lower()}).status_code == 403
    r = desktop.post("/api/v1/auth/sign-in", json={"code": f" {code.replace('-', '').lower()} "}, headers=H)
    assert r.status_code == 200, r.text
    assert desktop.get("/api/v1/me").json()["user"]["id"] == phone.get("/api/v1/me").json()["user"]["id"]
    # One use only, and a used code can't be replayed on a third device.
    r = TestClient(app).post("/api/v1/auth/sign-in", json={"code": code}, headers=H)
    assert r.json()["error"]["code"] == "CODE_INVALID"


def test_sign_in_code_expires(api, factory):
    app, codes = api
    phone = signup(app, codes[0], "kai")
    code = phone.post("/api/v1/auth/sign-in-codes", headers=H).json()["code"]
    with factory() as s, s.begin():
        s.execute(update(SignInCode).values(expires_at=SignInCode.created_at))
    r = TestClient(app).post("/api/v1/auth/sign-in", json={"code": code}, headers=H)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "CODE_INVALID")


def test_stream_holds_no_database_connection_while_open(api, factory):
    app, codes = api
    assert TestClient(app).get("/api/v1/stream").status_code == 401
    kai = signup(app, codes[0], "kai")
    pool = factory.kw["bind"].pool
    with kai.stream("GET", "/api/v1/stream") as r:
        assert r.status_code == 200
        assert next(r.iter_text()).startswith("retry:")
        assert pool.checkedout() == 0  # sign-in was checked on a session already returned to the pool


def test_offered_duel_stat_reaches_the_duel_window(api, world):
    """2026-10-23: gold-at-15 was the only duel offered, but the request schema still rejected it (422)."""
    app, codes = api
    kai = signup(app, codes[0], "kai")
    url = f"/api/v1/events/{world['fixture']}/duels"
    r = kai.post(url, json={"game_index": 1, "role": "mid", "stat": "gold15"}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] in ("NOT_OPEN", "NO_LINEUP")  # past validation
    r = kai.post(url, json={"game_index": 1, "role": "mid", "stat": "assists"}, headers=H)
    assert r.status_code == 422
    assert r.json()["error"] == {**r.json()["error"], "code": "INVALID_REQUEST", "details": {"fields": ["stat"]}}


def test_rivals_table_and_reactions_after_lock(api, factory, world):
    """D-034: the match table hides friends' open picks (A-010); reactions only on a friend's locked pick."""
    app, codes = api
    kai, mika = signup(app, codes[0], "kai"), signup(app, codes[1], "mika")
    atlas, nova = outcome_id(factory, world["market"], "A"), outcome_id(factory, world["market"], "B")
    for client, outcome, stake, key in ((kai, atlas, 400, "k1"), (mika, nova, 200, "m1")):
        q = client.post("/api/v1/quotes", json={"items": [{"outcome_id": str(outcome), "stake_rc": stake}]},
                        headers=H).json()
        r = client.post("/api/v1/tickets", headers={**H, "Idempotency-Key": key},
                        json={"quote_id": q["quote_id"], "confirm_odds_versions": {str(outcome): 1}})
        assert r.status_code == 201, r.text
    event = str(world["fixture"])
    before = mika.get(f"/api/v1/events/{event}/league").json()
    assert [r["user"]["handle"] for r in before["table"]] == ["mika"]  # kai's open pick stays hidden
    kai_pick = kai.get("/api/v1/me/picks").json()["picks"][0]["id"]
    r = mika.post(f"/api/v1/picks/{kai_pick}/reactions", json={"phrase": "sweating"}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_LOCKED"

    with factory() as s, s.begin():
        s.execute(update(Market).values(state="LOCKED"))
    after = mika.get(f"/api/v1/events/{event}/league").json()
    rows = {r["user"]["handle"]: r for r in after["table"]}
    assert set(rows) == {"kai", "mika"} and rows["kai"]["riding"] == 400 and rows["mika"]["you"]
    assert rows["kai"]["potential"] == 648 - 400 and rows["mika"]["potential"] == 480 - 200  # if both win
    r = mika.post(f"/api/v1/picks/{kai_pick}/reactions", json={"phrase": "sweating"}, headers=H)
    again = mika.post(f"/api/v1/picks/{kai_pick}/reactions", json={"phrase": "sweating"}, headers=H)
    assert r.status_code == 200 and len(again.json()["reactions"]) == 1  # once per phrase
    reaction = again.json()["reactions"][0]
    assert (reaction["from"]["handle"], reaction["to"]["handle"], reaction["text"]) == ("mika", "kai", "You're sweating")
    assert kai.post(f"/api/v1/picks/{kai_pick}/reactions", json={"phrase": "gg"}, headers=H).json()["error"]["code"] == "OWN_PICK"
    assert mika.post(f"/api/v1/picks/{kai_pick}/reactions", json={"phrase": "lol"}, headers=H).status_code == 422
    with factory() as s:
        ev = s.execute(select(OutboxEvent).where(OutboxEvent.type == "reaction.created")).scalar_one()
        assert ev.payload["text"] == "You're sweating" and ev.payload["from"]


def test_a_close_that_follows_the_game_is_not_a_countdown_until_it_loads(api, factory, world):
    """Through-draft markets close at 3:00 of game time; before the game loads close_at is only a backstop."""
    app, codes = api
    kai = signup(app, codes[0], "kai")
    with factory() as s, s.begin():
        s.get(Market, world["market"]).params = {"through_draft": True}
    event = str(world["fixture"])
    assert kai.get(f"/api/v1/events/{event}").json()["markets"][0]["close_known"] is False
    with factory() as s, s.begin():
        s.add(Game(fixture_id=world["fixture"], provider_id="g1", game_index=1, state="inProgress",
                   started_at=s.get(Fixture, world["fixture"]).scheduled_at))
    assert kai.get(f"/api/v1/events/{event}").json()["markets"][0]["close_known"] is True


def test_cancel_a_pick_before_its_market_locks(api, factory, world):
    """D-038: your own open pick comes back in full until its market locks; it never settles."""
    from rift.settlement import Grade, apply_grade

    app, codes = api
    kai, mika = signup(app, codes[0], "kai"), signup(app, codes[1], "mika")
    before = kai.get("/api/v1/me").json()["wallet"]["available_rc"]
    atlas = outcome_id(factory, world["market"], "A")
    q = kai.post("/api/v1/quotes", json={"items": [{"outcome_id": str(atlas), "stake_rc": 300}]}, headers=H).json()
    kai.post("/api/v1/tickets", headers={**H, "Idempotency-Key": "c1"},
             json={"quote_id": q["quote_id"], "confirm_odds_versions": {str(atlas): 1}})
    pick = kai.get("/api/v1/me/picks").json()["picks"][0]["id"]
    assert mika.post(f"/api/v1/picks/{pick}/cancel", headers=H).status_code == 404  # not yours

    r = kai.post(f"/api/v1/picks/{pick}/cancel", headers=H)
    assert r.status_code == 200 and r.json()["pick"]["status"] == "CANCELLED"
    assert r.json()["wallet"]["available_rc"] == before and r.json()["wallet"]["open_stake_rc"] == 0
    assert kai.post(f"/api/v1/picks/{pick}/cancel", headers=H).json()["error"]["code"] == "NOT_CANCELLABLE"

    # A pick on a locked market stands.
    q = kai.post("/api/v1/quotes", json={"items": [{"outcome_id": str(atlas), "stake_rc": 200}]}, headers=H).json()
    kai.post("/api/v1/tickets", headers={**H, "Idempotency-Key": "c2"},
             json={"quote_id": q["quote_id"], "confirm_odds_versions": {str(atlas): 1}})
    second = next(p["id"] for p in kai.get("/api/v1/me/picks?state=open").json()["picks"])
    with factory() as s, s.begin():
        s.execute(update(Market).values(state="LOCKED"))
    assert kai.post(f"/api/v1/picks/{second}/cancel", headers=H).json()["error"]["code"] == "MARKET_LOCKED"

    # Settling the market pays the standing pick and never touches the cancelled one.
    with factory() as s, s.begin():
        apply_grade(s, world["market"], Grade("RESULT", ["A"], "test"), T0 + timedelta(days=4000))
    picks = {p["id"]: p for p in kai.get("/api/v1/me/picks").json()["picks"]}
    assert picks[pick]["status"] == "CANCELLED" and picks[pick]["return_rc"] == 300  # the full refund
    assert picks[second]["status"] == "WON"


def test_today_net_counts_picks_settled_today_only(api, factory, world):
    """The top bar's figure: return minus stake of picks settled on the venue's day, not grants."""
    from sqlalchemy import select as sel_

    from rift.api.views import today_net
    from rift.models import Selection, Wallet
    from rift.settlement import Grade, apply_grade

    app, codes = api
    kai = signup(app, codes[0], "kai")
    atlas = outcome_id(factory, world["market"], "A")
    q = kai.post("/api/v1/quotes", json={"items": [{"outcome_id": str(atlas), "stake_rc": 100}]}, headers=H).json()
    kai.post("/api/v1/tickets", headers={**H, "Idempotency-Key": "t1"},
             json={"quote_id": q["quote_id"], "confirm_odds_versions": {str(atlas): 1}})
    settled_at = T0 + timedelta(hours=6)
    with factory() as s, s.begin():
        apply_grade(s, world["market"], Grade("RESULT", ["A"], "test"), settled_at)
    with factory() as s:
        wallet = s.execute(sel_(Wallet).join(Selection, Selection.user_id == Wallet.user_id)).scalars().first()
        assert today_net(s, wallet, now=settled_at) == 62  # 100 at 1.62
        assert today_net(s, wallet, now=settled_at + timedelta(days=1)) == 0  # a new day starts at zero
        # The league's daily standings use the same day: a win today, then a fresh day with the season record kept.
        from rift.api.views import standings
        from rift.models import Season

        season = s.get(Season, wallet.season_id)
        row = standings(s, season, now=settled_at)[0]
        assert (row["won"], row["lost"], row["won_today"], row["lost_today"], row["today_net_rc"]) == (1, 0, 1, 0, 62)
        row = standings(s, season, now=settled_at + timedelta(days=1))[0]
        assert (row["won"], row["won_today"]) == (1, 0)
