"""Results before payout (D-032): live calls from the game's timeline, never written anywhere."""

import uuid

from rift.calls import live_call
from rift.models import Fixture, Game, Market

A, B = uuid.uuid4(), uuid.uuid4()


def _game(**tl):
    participants = {str(i): {"side": "blue" if i <= 5 else "red", "champion": f"C{i}", "role": role,
                             "player_id": f"p{i}", "name": f"P{i}"}
                    for i, role in zip(range(1, 11), ["top", "jungle", "mid", "bottom", "support"] * 2, strict=True)}
    return Game(game_index=1, blue_team_id=A, red_team_id=B, timeline={"participants": participants, **tl})


def _market(kind, scope="GAME", **params):
    return Market(kind=kind, scope=scope, params={"game_index": 1, **params})


FIXTURE = Fixture(team_a_id=A, team_b_id=B)


def test_nothing_is_called_before_the_game_loads():
    assert live_call(_market("first_blood"), FIXTURE, Game(game_index=1, timeline=None)) is None


def test_firsts_are_called_the_moment_they_happen():
    game = _game(firsts={"blood": {"side": "red", "team_id": str(B), "at_s": 200}})
    call = live_call(_market("first_blood"), FIXTURE, game)
    assert call.codes == ["B"] and not call.final and not call.void
    assert live_call(_market("first_tower"), FIXTURE, game) is None  # not yet


def test_the_draft_is_called_from_the_first_frame():
    game = _game()
    assert live_call(_market("champion_picked", champion="C3"), FIXTURE, game).codes == ["YES"]
    assert live_call(_market("champion_picked", champion="Zed"), FIXTURE, game).codes == ["NO"]
    assert live_call(_market("champion_picked", champion="C3", side="B"), FIXTURE, game).codes == ["NO"]


def test_baron_before_25_and_kill_lines_once_decided():
    early = _game(firsts={"baron": {"side": "blue", "team_id": str(A), "at_s": 1300}})
    assert live_call(_market("baron_before"), FIXTURE, early).codes == ["YES"]
    late = _game(firsts={}, live={"clock_s": 1520, "kills": {"blue": 12, "red": 14}})
    assert live_call(_market("baron_before"), FIXTURE, late).codes == ["NO"]
    assert live_call(_market("total_kills_game", line="24.5"), FIXTURE, late).codes == ["OVER"]
    assert live_call(_market("total_kills_game", line="30.5"), FIXTURE, late) is None  # under only at the end
