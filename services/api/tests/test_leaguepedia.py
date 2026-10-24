import uuid
from datetime import UTC, datetime

import httpx
import pytest

from rift.adapters.leaguepedia import (
    LeaguepediaClient,
    LeaguepediaGame,
    LeaguepediaSource,
    MockLeaguepedia,
    make_source,
)
from rift.champions import champion_id, champion_key
from rift.config import Settings
from rift.ingest import infer_game_winners, sync_drafts
from rift.models import Fixture, Game, Team


def settings(**kwargs):
    return Settings(_env_file=None, leaguepedia_mode="live", leaguepedia_bot_user="Test@RiftExchange",
                    leaguepedia_bot_password="test-secret", **kwargs)


GAME = {"title": {"Team1": "Atlas", "Team2": "Nova", "WinTeam": "Atlas", "N GameInMatch": "1",
                  "DateTime UTC": "2026-10-19 12:00:00", "Team1Bans": "Ahri,Jax", "Team2Bans": "Vi"}}


def client(cargo, *, login=None, status=200):
    def respond(request):
        if request.method == "POST":
            return httpx.Response(200, json={"login": login or {"result": "Success"}})
        if request.url.params["action"] == "query":
            return httpx.Response(200, json={"query": {"tokens": {"logintoken": "token"}}})
        if request.url.params.get("tables") == "TeamRedirects=TR":
            name = request.url.params["where"].split('"')[1]
            return httpx.Response(200, json={"cargoquery": [{"title": {"Canonical": name}}]})
        return httpx.Response(status, json=cargo)

    return LeaguepediaClient(settings(), httpx.Client(transport=httpx.MockTransport(respond)))


@pytest.mark.parametrize("user,password", [("", ""), ("Test", ""), ("", "secret"), (" ", "secret")])
def test_live_never_silently_falls_back_to_mock(user, password):
    with pytest.raises(RuntimeError, match="requires both"):
        make_source(Settings(_env_file=None, leaguepedia_mode="live",
                             leaguepedia_bot_user=user, leaguepedia_bot_password=password))
    assert isinstance(make_source(Settings(_env_file=None, leaguepedia_mode="mock")), MockLeaguepedia)


def test_login_failure_does_not_echo_provider_response():
    source = client({}, login={"result": "Failed", "reason": "test-secret"})
    with pytest.raises(RuntimeError, match="login failed") as error:
        source.check_access()
    assert "test-secret" not in str(error.value)
    assert "test-secret" not in repr(settings())


def test_cargo_errors_cannot_look_like_empty_data():
    source = client({"error": {"code": "permissiondenied", "info": "test-secret"}})
    with pytest.raises(RuntimeError, match="API returned an error") as error:
        source.series_games("Atlas", "Nova", datetime(2026, 10, 19))
    assert "test-secret" not in str(error.value)


def test_probe_requires_real_parseable_rows():
    source = client({"cargoquery": [GAME]})
    source.check_access()
    games = source.series_games("Atlas", "Nova", datetime(2026, 10, 19))
    assert games[0].winner == 1
    assert games[0].team1_bans == ["Ahri", "Jax"]
    for response in ({"cargoquery": []}, {}):
        with pytest.raises(RuntimeError, match="no game rows"):
            client(response).check_access()
    with pytest.raises(KeyError):
        client({"cargoquery": [{"title": {}}]}).check_access()


def test_http_failure_is_not_coverage():
    with pytest.raises(httpx.HTTPStatusError):
        client({}, status=429).check_access()


def test_probe_rejects_unknown_winner():
    row = {"title": dict(GAME["title"], WinTeam="")}
    with pytest.raises(RuntimeError, match="no recognized winner"):
        client({"cargoquery": [row]}).check_access()


def test_bot_secret_files(tmp_path, monkeypatch):
    for name, value in (("USER", "Test@RiftExchange"), ("PASSWORD", "test-secret")):
        path = tmp_path / name
        path.write_text(value + "\n")
        monkeypatch.setenv(f"RIFT_LEAGUEPEDIA_BOT_{name}_FILE", str(path))
    config = Settings(_env_file=None, leaguepedia_mode="live")
    assert config.leaguepedia_bot_user == "Test@RiftExchange"
    assert config.leaguepedia_bot_password == "test-secret"


def test_series_crosses_midnight_and_resolves_sponsor_names():
    def respond(request):
        params = request.url.params
        if request.method == "POST":
            return httpx.Response(200, json={"login": {"result": "Success"}})
        if params["action"] == "query":
            return httpx.Response(200, json={"query": {"tokens": {"logintoken": "token"}}})
        if params["tables"] == "TeamRedirects=TR":
            name = params["where"].split('"')[1]
            return httpx.Response(200, json={"cargoquery": [{"title": {"Canonical": name.removesuffix(" Kia")}}]})
        assert 'SG.Team2="Cloud9"' in params["where"]
        assert 'SG.DateTime_UTC >= "2026-10-19 17:00:00"' in params["where"]
        assert 'SG.DateTime_UTC <= "2026-10-20 11:00:00"' in params["where"]
        row = {"title": dict(GAME["title"], Team2="Cloud9", WinTeam="Cloud9",
                             **{"DateTime UTC": "2026-10-20 00:15:00"})}
        return httpx.Response(200, json={"cargoquery": [row]})

    source = LeaguepediaClient(settings(), httpx.Client(transport=httpx.MockTransport(respond)))
    games = source.series_games("Atlas", "Cloud9 Kia", datetime.fromisoformat("2026-10-19T16:00:00-07:00"))
    assert games[0].team2 == "Cloud9 Kia"
    assert games[0].winner == 2


def test_duplicate_game_numbers_cannot_select_the_wrong_series():
    with pytest.raises(RuntimeError, match="ambiguous games"):
        client({"cargoquery": [GAME, GAME]}).series_games("Atlas", "Nova", datetime(2026, 10, 19))


def test_provider_outage_does_not_block_startup():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503)

    source = LeaguepediaClient(settings(), httpx.Client(transport=httpx.MockTransport(respond)))
    assert calls == []
    with pytest.raises(httpx.HTTPStatusError):
        source.check_access()


def test_rows_map_back_case_insensitively():
    row = {"title": dict(GAME["title"], Team1="ATLAS", Team2="nova", WinTeam="nova")}
    games = client({"cargoquery": [row]}).series_games("Atlas", "Nova", datetime(2026, 10, 19))
    assert (games[0].team1, games[0].team2, games[0].winner) == ("Atlas", "Nova", 2)
    row = {"title": dict(GAME["title"], Team2="Orbit", WinTeam="Orbit")}
    with pytest.raises(RuntimeError, match="unexpected team"):
        client({"cargoquery": [row]}).series_games("Atlas", "Nova", datetime(2026, 10, 19))


class FailingSource(LeaguepediaSource):
    available = True

    def series_games(self, team_a, team_b, on):
        raise RuntimeError("Leaguepedia returned ambiguous games for the fixture")

    series_drafts = series_games


class Teams:
    def __init__(self, *teams):
        self.teams = {t.id: t for t in teams}

    def get(self, model, key):
        return self.teams[key]


def test_secondary_failure_leaves_only_that_fixture_unresolved():
    atlas, nova = Team(id=uuid.uuid4(), name="Atlas"), Team(id=uuid.uuid4(), name="Nova")
    fixture = Fixture(provider_id="f1", team_a_id=atlas.id, team_b_id=nova.id, team_a_wins=1, team_b_wins=1,
                      scheduled_at=datetime(2026, 10, 23, 17, tzinfo=UTC))
    games = [Game(game_index=i, state="completed", winner_team_id=None) for i in (1, 2)]
    infer_game_winners(Teams(atlas, nova), fixture, games, FailingSource(), datetime.now(UTC))
    assert [g.winner_team_id for g in games] == [None, None]


PB = {f"Team{t}{kind}{i}": v for t, picks, roles in (
    (1, ["Lee Sin", "Wukong", "K'Sante", "Jinx", "Nautilus"], ["Jungle", "Top", "Mid", "Bot", "Support"]),
    (2, ["Nunu & Willump", "Kai'Sa", "Renata Glasc", "Rek'Sai", "Dr. Mundo"],
     ["Jungle", "Bot", "Support", "Mid", "Top"]))
    for kind, values in (("Pick", picks), ("Role", roles)) for i, v in enumerate(values, 1)}


@pytest.mark.parametrize("display,ident", [
    ("Lee Sin", "LeeSin"), ("Wukong", "MonkeyKing"), ("K'Sante", "KSante"), ("Nunu & Willump", "Nunu"),
    ("Kai'Sa", "Kaisa"), ("Dr. Mundo", "DrMundo"), ("Jarvan IV", "JarvanIV"), ("Renata Glasc", "Renata"),
    ("Cho'Gath", "Chogath"), ("LeBlanc", "Leblanc"), ("Ahri", "Ahri"), ("None", None), ("", None),
    ("Loss of Ban", None)])
def test_display_names_normalise_to_livestats_ids(display, ident):
    assert champion_id(display) == ident


def test_champion_keys_agree_across_spellings():
    assert champion_key("KaiSa") == champion_key("Kaisa") == champion_key("Kai'Sa")
    assert champion_key("Wukong") == champion_key("MonkeyKing")
    assert champion_key("RenataGlasc") == champion_key("Renata")
    with pytest.raises(ValueError):
        champion_id("404")


def test_draft_query_joins_picks_and_bans_on_game_id():
    seen = {}

    def respond(request):
        params = request.url.params
        if request.method == "POST":
            return httpx.Response(200, json={"login": {"result": "Success"}})
        if params["action"] == "query":
            return httpx.Response(200, json={"query": {"tokens": {"logintoken": "token"}}})
        if params["tables"] == "TeamRedirects=TR":
            return httpx.Response(200, json={"cargoquery": [{"title": {"Canonical": params["where"].split('"')[1]}}]})
        seen.update(params)
        row = dict(GAME["title"], PBTeam1="Atlas", PBTeam2="Nova", **PB)
        return httpx.Response(200, json={"cargoquery": [{"title": row}]})

    source = LeaguepediaClient(settings(), httpx.Client(transport=httpx.MockTransport(respond)))
    games = source.series_drafts("Atlas", "Nova", datetime(2026, 10, 19))
    assert seen["tables"] == "ScoreboardGames=SG, PicksAndBansS7=PB" and seen["join_on"] == "SG.GameId=PB.GameId"
    assert "PB.Team1Pick1" in seen["fields"] and "PB.Team2Role5" in seen["fields"]
    draft = games[0].draft
    assert draft.team1_picks[0] == "Lee Sin" and draft.team2_picks[1] == "Kai'Sa"
    assert draft.team1_roles == ["jungle", "top", "mid", "bottom", "support"]


def test_partial_or_mismatched_pick_rows_are_not_a_draft():
    base = dict(GAME["title"], PBTeam1="Atlas", PBTeam2="Nova", **PB)
    parse = LeaguepediaClient._parse_games
    assert parse([{"title": base}])[0].draft is not None
    assert parse([{"title": dict(base, Team2Pick5="")}])[0].draft is None
    assert parse([{"title": dict(base, PBTeam1="Nova", PBTeam2="Atlas")}])[0].draft is None
    assert parse([{"title": dict(base, PBTeam1="", PBTeam2="")}])[0].draft is None  # no PB row joined
    assert parse([GAME])[0].draft is None  # winner query: no PB fields at all


def lp_game(n, team1="Nova", team2="Atlas", draft=True):
    """Leaguepedia game where `team1` (blue) is Nova, as in the livestats game below."""
    picks = LeaguepediaClient._parse_draft(dict(PB, Team1=team1, Team2=team2, PBTeam1=team1, PBTeam2=team2))
    return LeaguepediaGame(team1, team2, 1, n, datetime(2026, 10, 23, 17), ["Lee Sin", "Wukong", "None"],
                           ["K'Sante", "Ahri"], picks if draft else None)


def test_bans_and_pick_order_are_stored_on_completed_games(factory, world):
    with factory() as s, s.begin():
        s.get(Fixture, world["fixture"]).status = "LIVE"
        for i, state in ((1, "completed"), (2, "completed"), (3, "unstarted")):
            s.add(Game(fixture_id=world["fixture"], provider_id=f"g{i}", game_index=i, state=state,
                       blue_team_id=world["team_b"], red_team_id=world["team_a"]))
    source = MockLeaguepedia({("Atlas", "Nova"): [lp_game(1), lp_game(2, draft=False)]})
    now = datetime(2026, 10, 23, 20, tzinfo=UTC)
    with factory() as s, s.begin():
        assert sync_drafts(s, s.get(Fixture, world["fixture"]), source, now) == 2
    with factory() as s, s.begin():
        games = {g.game_index: g for g in s.query(Game)}
        assert games[1].bans == {
            "source": "leaguepedia", "blue": ["LeeSin", "MonkeyKing"], "red": ["KSante", "Ahri"],
            "first_pick": "LeeSin", "first_pick_side": "blue",
            "picks": {"blue": ["LeeSin", "MonkeyKing", "KSante", "Jinx", "Nautilus"],
                      "red": ["Nunu", "Kaisa", "Renata", "RekSai", "DrMundo"]},
            "roles": {"blue": ["jungle", "top", "mid", "bottom", "support"],
                      "red": ["jungle", "bottom", "support", "mid", "top"]},
            "sides": {"blue": "B", "red": "A"}, "length_s": None}
        assert games[2].bans["blue"] == ["LeeSin", "MonkeyKing"] and games[2].bans["first_pick"] is None
        assert games[3].bans is None
        # Game 1 is done; Game 2 is asked for again until its pick order appears.
        source.calls = 0
        assert sync_drafts(s, s.get(Fixture, world["fixture"]), source, now) == 0 and source.calls == 1
        games[2].bans = {**games[2].bans, "first_pick": "LeeSin"}
        source.calls = 0
        assert sync_drafts(s, s.get(Fixture, world["fixture"]), source, now) == 0 and source.calls == 0


def test_sides_that_disagree_with_livestats_store_nothing(factory, world):
    with factory() as s, s.begin():
        s.add(Game(fixture_id=world["fixture"], provider_id="g1", game_index=1, state="completed",
                   blue_team_id=world["team_a"], red_team_id=world["team_b"]))
    with factory() as s, s.begin():
        fixture = s.get(Fixture, world["fixture"])
        assert sync_drafts(s, fixture, MockLeaguepedia({("Atlas", "Nova"): [lp_game(1)]}),
                           datetime.now(UTC)) == 0
        assert sync_drafts(s, fixture, FailingSource(), datetime.now(UTC)) == 0  # contained, not raised
        assert s.query(Game).one().bans is None
