from datetime import datetime

import httpx
import pytest

from rift.adapters.leaguepedia import LeaguepediaClient, MockLeaguepedia, make_source
from rift.config import Settings


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
        return httpx.Response(status, json=cargo)

    return LeaguepediaClient(settings(), httpx.Client(transport=httpx.MockTransport(respond)))


@pytest.mark.parametrize("user,password", [("", ""), ("Test", ""), ("", "secret"), (" ", "secret")])
def test_live_never_silently_falls_back_to_mock(user, password):
    with pytest.raises(RuntimeError, match="requires both"):
        make_source(Settings(_env_file=None, leaguepedia_mode="live",
                             leaguepedia_bot_user=user, leaguepedia_bot_password=password))
    assert isinstance(make_source(Settings(_env_file=None, leaguepedia_mode="mock")), MockLeaguepedia)


def test_login_failure_does_not_echo_provider_response():
    with pytest.raises(RuntimeError, match="login failed") as error:
        client({}, login={"result": "Failed", "reason": "test-secret"})
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
