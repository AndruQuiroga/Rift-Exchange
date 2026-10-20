"""Isolated tests: no rift_test connection or shared DB truncation."""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from rift import draft, markets, props, reference
from rift.adapters.leaguepedia import LeaguepediaDraft, LeaguepediaGame, MockLeaguepedia
from rift.adapters.lolesports import GameRef, GameStats, MatchDetail, PlayerLine, ScheduleMatch
from rift.models import Base, Game, ReferenceGame

T = datetime(2026, 8, 1, tzinfo=UTC)
CUTOFF = datetime(2026, 10, 1, tzinfo=UTC)
ROLES = ("top", "jungle", "mid", "bottom", "support")


@pytest.fixture
def isolated():
    engine = create_engine("sqlite://")
    ReferenceGame.__table__.create(engine)
    with Session(engine) as session:
        real_scalars = session.scalars
        session.scalars = lambda statement: [] if statement.column_descriptions[0].get("entity") is reference.Team else real_scalars(statement)
        yield session
    engine.dispose()


def event(name="summer", start=T, category="regional"):
    return reference.ReferenceEvent(name, "league", "lck", category, start, CUTOFF)


def provider(count=1):
    client = Mock()
    matches = [ScheduleMatch(f"m{i}", "lck", T + timedelta(days=i), "completed", "Finals", 1, [])
               for i in range(count)]
    client.schedule_since.return_value = matches
    client.event_details.side_effect = lambda mid: MatchDetail(mid, [("a", "Alpha", 1), ("b", "Beta", 0)],
        [GameRef(f"g{mid[1:]}", 1, "completed", "a", "b")])
    def stats(gid, now):
        at = T + timedelta(days=int(gid[1:]))
        return GameStats(gid, "26.16", "finished", at, at + timedelta(minutes=30), "a", "b", [
            PlayerLine(i, f"p{i}", f"Player {i}", "blue" if i < 5 else "red", ROLES[i % 5],
                       f"Champion{i}", i, 0, 0) for i in range(10)])
    client.final_stats.side_effect = stats
    return client


def secondary():
    d = LeaguepediaDraft([f"Champion{i}" for i in range(5)], [f"Champion{i}" for i in range(5, 10)],
                        list(ROLES), list(ROLES))
    return MockLeaguepedia({("Alpha", "Beta"): [LeaguepediaGame("Alpha", "Beta", 1, 1, T,
        [f"Ban{i}" for i in range(5)], [f"Ban{i}" for i in range(5, 10)], d)]})


def test_metadata_registered_without_reference_import():
    assert Base.metadata.tables["reference_games"] is ReferenceGame.__table__


def test_idempotent_stats_and_later_draft_enrichment(isolated):
    client = provider()
    first = reference.ingest_references(isolated, client, MockLeaguepedia(), [event()], CUTOFF)
    assert first["stored"] == first["with_stats"] == 1 and first["with_bans"] == 0
    original = isolated.get(ReferenceGame, "g0").payload["players"]
    enriched = reference.ingest_references(isolated, client, secondary(), [event()], CUTOFF)
    assert enriched["stored"] == 0 and enriched["enriched"] == enriched["with_bans"] == 1
    again = reference.ingest_references(isolated, client, secondary(), [event()], CUTOFF)
    assert again["attempted"] == 0
    assert isolated.get(ReferenceGame, "g0").payload["players"] == original
    assert len(list(isolated.scalars(select(ReferenceGame)))) == 1


def test_resumes_to_later_matches(isolated):
    client = provider(3)
    cursor = (0, 0, 0)
    for _ in range(3):
        report = reference.ingest_references(isolated, client, MockLeaguepedia(), [event()], CUTOFF,
                                             max_matches=1, cursor=cursor)
        cursor = report["next_cursor"]
    assert report["next_cursor"] is None
    assert len(list(isolated.scalars(select(ReferenceGame)))) == 3
    assert report["coverage"] == "unverified"


def test_only_latest_regional_split_queried(isolated):
    client = provider()
    reference.ingest_references(isolated, client, MockLeaguepedia(),
        [reference.ReferenceEvent("spring", "league", "lck", "regional",
                                 T - timedelta(days=120), T - timedelta(days=45)), event()], CUTOFF)
    assert client.schedule_since.call_count == 1
    assert client.schedule_since.call_args.args[1] == T


@pytest.mark.parametrize("mutate", ["future", "partial", "duplicate", "wrong_id"])
def test_invalid_finals_remain_missing(isolated, mutate):
    client = provider()
    stats = client.final_stats("g0", CUTOFF)
    if mutate == "future":
        stats.last_frame_at = CUTOFF + timedelta(minutes=1)
    elif mutate == "partial":
        stats.players.pop()
    elif mutate == "duplicate":
        stats.players[0].champion = stats.players[1].champion
    else:
        stats.game_id = "other"
    client.final_stats.side_effect = None
    client.final_stats.return_value = stats
    report = reference.ingest_references(isolated, client, secondary(), [event()], CUTOFF)
    assert report["missing"] == 1 and report["stored"] == 0


def test_provider_draft_failure_keeps_stats(isolated):
    source = Mock(available=True)
    source.series_drafts.side_effect = RuntimeError("unavailable")
    report = reference.ingest_references(isolated, provider(), source, [event()], CUTOFF)
    assert report["stored"] == 1 and report["draft_errors"] == 1 and report["with_bans"] == 0


def test_bad_bounds_fail_before_network(isolated):
    client = provider()
    with pytest.raises(ValueError):
        reference.ingest_references(isolated, client, secondary(), [event(start=T.replace(year=2025))], CUTOFF)
    client.schedule_since.assert_not_called()


def test_selection_dedup_latest_split_and_budgets():
    season = NS(id=uuid.uuid4())
    fixture = NS(id=uuid.uuid4(), scheduled_at=CUTOFF)
    current = Game(provider_id="current", state="completed")
    refs = [NS(played_at=T, provider_id="duplicate", category="international", event="msi", payload={})]
    refs += [NS(played_at=T, provider_id=f"int{i}", category="international", event=f"event{i % 3}", payload={}) for i in range(60)]
    refs += [NS(played_at=T, provider_id="spring", category="regional", event="spring",
                payload={"league_slug": "lck", "window_start": "2026-01-01"}),
             NS(played_at=T, provider_id="summer", category="regional", event="summer",
                payload={"league_slug": "lck", "window_start": "2026-07-01"})]
    session = Mock()
    session.scalars.side_effect = [[fixture], [current], ["duplicate", "current"],
                                   [r for r in refs if r.category == "international"],
                                   [r for r in refs if r.category == "regional"]]
    rows = reference.observations(session, season)
    assert rows[0] == (current, 1)
    assert not {"duplicate", "spring"}.intersection(g.provider_id for g, _ in rows)
    assert "summer" in {g.provider_id for g, _ in rows}
    assert sum(w for _, w in rows[1:]) <= 40
    assert sum(w for g, w in rows if g.provider_id.startswith("int")) == 20


def test_weighted_draft_and_kill_priors(monkeypatch):
    def game(champ, kills):
        return NS(stats={"players": [{"champion": champ, "role": "mid", "kills": kills}]},
                  stats_complete=True, bans={"blue": [champ], "red": []})
    monkeypatch.setattr(reference, "observations", lambda *a, **k: [(game("Ahri", 10), 1), (game("Azir", 2), .5)])
    monkeypatch.setattr(props, "timeline_data", lambda *a: None)
    rates = draft.tournament_rates(None, None)
    assert rates.games == rates.ban_games == 1.5
    assert rates.picked["Ahri"] == rates.banned["Ahri"] == pytest.approx(2 / 3)
    stats = markets.tournament_stats(None, None)
    assert stats.games == 1.5 and sum(stats.kill_totals) / len(stats.kill_totals) == pytest.approx(22 / 3)


def test_player_weights_and_missing_stats():
    data = props.TimelineData()
    data.reference_samples = [("p", "mid", "Ahri", 8., .5)] * 10
    mean, var = props._player_estimate(data, "p", "mid", "kills", "Ahri")
    assert mean == 8 and var >= 1
    assert props._player_estimate(data, "p", "mid", "cs15") is None
    assert props._player_estimate(data, "p", "mid", "damage") is None

def test_discovery_uses_feed_ids_and_latest_split():
    client = Mock()
    client.settings.lolesports_api = "https://example.test"
    client.leagues.return_value = {"lck": "actual-league", "msi": "msi-id"}
    def tournaments(url, params):
        if params["leagueId"] == "msi-id":
            records = [{"id": "msi26", "slug": "msi_2026", "startDate": "2026-06-01", "endDate": "2026-06-20"}]
        else:
            records = [{"id": "spring", "slug": "spring26", "startDate": "2026-01-01", "endDate": "2026-03-01"},
                       {"id": "summer", "slug": "summer26", "startDate": "2026-07-01", "endDate": "2026-09-01"}]
        # Real endpoint omits league id in the response; request leagueId supplies that identity.
        return {"data": {"leagues": [{"tournaments": records}]}}
    client._get.side_effect = tournaments
    events, _ = reference.discover_events(client, CUTOFF)
    assert {e.tournament_id for e in events} == {"summer", "msi26"}
    assert next(e for e in events if e.category == "regional").end == datetime(2026, 9, 2, tzinfo=UTC)


def test_reference_migration_matches_metadata():
    import importlib.util
    from pathlib import Path

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import MetaData
    path = Path(__file__).parents[1] / "migrations/versions/e6f7a8b9c0d1_reference_games.py"
    spec = importlib.util.spec_from_file_location("reference_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()
        target = MetaData()
        ReferenceGame.__table__.to_metadata(target)
        assert compare_metadata(context, target) == []
    engine.dispose()


def test_duel_passes_champion_context(monkeypatch):
    seen = []
    def estimate(data, pid, role, stat, champion=None):
        seen.append(champion)
        return 1., 1.
    monkeypatch.setattr(props, "_player_estimate", estimate)
    props.duel_probability(props.TimelineData(), {"player_id": "a", "champion": "Ahri"},
                           {"player_id": "b", "champion": "Azir"}, "mid", "kills")
    assert seen == ["Ahri", "Azir"]


def test_reference_evidence_can_unlock_before_worlds(monkeypatch):
    players = [{"champion": "Ahri", "role": "mid", "kills": 5}]
    g = NS(stats={"players": players}, stats_complete=True, bans={"blue": ["Azir"], "red": []})
    monkeypatch.setattr(reference, "observations", lambda *a, **k: [(g, .5)] * 32)
    monkeypatch.setattr(props, "timeline_data", lambda *a: None)
    rates = draft.tournament_rates(None, None)
    assert "banned" in draft.offered_scopes(rates)
    assert props._kill_dist(markets.tournament_stats(None, None)) is not None

def test_discovery_rejects_ambiguous_or_mismatched_wrappers():
    client = Mock()
    client.settings.lolesports_api = "https://example.test"
    client.leagues.return_value = {"lck": "expected"}
    tournament = {"id": "t", "slug": "split3", "startDate": "2026-07-01", "endDate": "2026-09-01"}
    for wrappers in ([{"tournaments": [tournament]}, {"tournaments": [tournament]}],
                     [{"id": "other", "tournaments": [tournament]}]):
        client._get.return_value = {"data": {"leagues": wrappers}}
        events, _ = reference.discover_events(client, CUTOFF)
        assert events == []

def test_category_queries_preserve_older_internationals():
    fixture = NS(id=uuid.uuid4(), scheduled_at=CUTOFF)
    intl = [NS(provider_id=f"i{i}", played_at=T, category="international", event="msi", payload={})
            for i in range(40)]
    regional = [NS(provider_id=f"r{i}", played_at=T + timedelta(days=10), category="regional", event="summer",
                   payload={"league_slug": "lck", "window_start": T.isoformat()}) for i in range(300)]
    session = Mock()
    session.scalars.side_effect = [[fixture], [], [], intl, regional]
    rows = reference.observations(session, NS(id=uuid.uuid4()))
    assert any(g.provider_id.startswith("i") for g, _ in rows)
    assert any(g.provider_id.startswith("r") for g, _ in rows)
    queries = [call.args[0].compile().params for call in session.scalars.call_args_list[-2:]]
    assert [q["category_1"] for q in queries] == ["international", "regional"]
    assert all(300 in q.values() for q in queries)


def test_current_champion_samples_condition_estimate():
    data = props.TimelineData(role={"mid": {"kills": [0.] * 6}})
    data.champion_samples = [("mid", "Ahri", "kills", 10., 1.)] * 6
    baseline = props._player_estimate(data, "new", "mid", "kills")
    conditioned = props._player_estimate(data, "new", "mid", "kills", "Ahri")
    assert conditioned[0] > baseline[0]
