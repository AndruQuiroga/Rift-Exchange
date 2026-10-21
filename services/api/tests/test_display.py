"""Display names: one table for teams, team prefixes stripped from player names."""

from types import SimpleNamespace

from rift.api.views import void_reason
from rift.display import player_name, relabel, team_name


def test_team_name_uses_table_then_tidies_shouted_names():
    assert team_name("GEN", "Gen.G Esports") == "Gen.G"
    assert team_name("XYZ", "SOME NEW TEAM") == "Some New Team"
    assert team_name("XYZ", "Mixed Case Team") == "Mixed Case Team"
    assert team_name("XYZ", "TSW") == "TSW"


def test_relabel_rewrites_old_snapshots():
    teams = [SimpleNamespace(code="BLG", name="BILIBILI GAMING"), SimpleNamespace(code="GEN", name="Gen.G Esports")]
    assert relabel("BILIBILI GAMING Swiss record", teams) == "Bilibili Gaming Swiss record"
    assert relabel("Gen.G Esports", teams) == "Gen.G"
    assert relabel("Over 25.5", teams) == "Over 25.5"
    assert relabel(None, teams) is None


def test_player_name_strips_only_a_known_team_prefix():
    codes = ["GEN", "IG"]
    assert player_name("GEN Kiin", codes) == "Kiin"
    assert player_name("IGTheShy", codes) == "TheShy"
    assert player_name("Faker", codes) == "Faker"
    assert player_name("IGOR", codes) == "IGOR"  # all caps after the code: not a prefix
    assert player_name("Gumayusi", ["GEN", "G"]) == "Gumayusi"


def test_void_reason_in_plain_words():
    pick = SimpleNamespace(status="VOID", settled_revision=1)
    early = SimpleNamespace(kind="first_blood", params={"early": True})
    series = SimpleNamespace(kind="series_winner", params={})
    void = lambda reason: SimpleNamespace(void=True, reason=reason)
    assert void_reason(pick, early, SimpleNamespace(void=False, reason=None)) == "Placed after 3:00"
    assert void_reason(pick, series, None) == "Placed after the start"
    assert void_reason(pick, early, void("Exact tie (void rule)")) == "Tie"
    assert void_reason(pick, series, void("Game 3 was not played")) == "Game 3 not played"
    assert void_reason(SimpleNamespace(status="WON"), series, None) is None
    moved = SimpleNamespace(status="VOID", settled_revision=0)
    assert void_reason(moved, SimpleNamespace(kind="swiss_record", params={}), None).startswith("Moved to the free")
