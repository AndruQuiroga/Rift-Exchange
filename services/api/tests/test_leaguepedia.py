import uuid
from datetime import UTC, datetime

import httpx
import pytest

from rift.adapters.leaguepedia import LeaguepediaClient, LeaguepediaSource, MockLeaguepedia, make_source
from rift.config import Settings
from rift.ingest import infer_game_winners
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
