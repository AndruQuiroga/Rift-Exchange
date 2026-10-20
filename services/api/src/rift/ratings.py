"""Level-1 team strength model (docs/spec/06_ODDS_ENGINE.md): game-level Elo with regional priors.

Each series contributes its individual game results (order unknown, so wins are interleaved).
International events carry the cross-region signal. Probabilities are shrunk toward 0.5 to avoid
overconfidence; the walk-forward backtest decides whether the model is labelled EXPERIMENTAL.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rift.domain.pricing import elo_expectation, series_win_probability
from rift.models import Fixture, HistoricalResult, Team, TeamRating

MODEL_KEY = "elo_v1"
REGION_PRIOR = {"LCK": 1600.0, "LPL": 1600.0, "LEC": 1510.0, "LCP": 1460.0, "LCS": 1450.0, "CBLOL": 1400.0}
DEFAULT_PRIOR = 1450.0
K = 12.0  # tuned on the walk-forward backtest (2026-10-20); lower K leans on regional priors
SHRINK = 0.85
INTERNATIONAL = {"worlds", "msi", "first_stand", "ewc_lol"}


@dataclass
class SeriesRecord:
    played_at: datetime
    league: str
    team_a: uuid.UUID
    team_b: uuid.UUID
    a_wins: int
    b_wins: int


@dataclass
class EloModel:
    priors: dict[uuid.UUID, float]
    ratings: dict[uuid.UUID, float] = field(default_factory=dict)
    games: dict[uuid.UUID, int] = field(default_factory=dict)

    def rating(self, team: uuid.UUID) -> float:
        return self.ratings.get(team, self.priors.get(team, DEFAULT_PRIOR))

    def game_probability(self, a: uuid.UUID, b: uuid.UUID) -> float:
        raw = elo_expectation(self.rating(a), self.rating(b))
        return 0.5 + SHRINK * (raw - 0.5)

    def update(self, rec: SeriesRecord) -> None:
        results = []
        wa, wb = rec.a_wins, rec.b_wins
        while wa or wb:  # interleave so series order does not bias the update
            if wa:
                results.append(1.0)
                wa -= 1
            if wb:
                results.append(0.0)
                wb -= 1
        for r in results:
            ra, rb = self.rating(rec.team_a), self.rating(rec.team_b)
            e = elo_expectation(ra, rb)
            self.ratings[rec.team_a] = ra + K * (r - e)
            self.ratings[rec.team_b] = rb - K * (r - e)
            self.games[rec.team_a] = self.games.get(rec.team_a, 0) + 1
            self.games[rec.team_b] = self.games.get(rec.team_b, 0) + 1


def load_records(session: Session, until: datetime | None = None) -> list[SeriesRecord]:
    recs = [SeriesRecord(r.played_at, r.league_slug, r.team_a_id, r.team_b_id, r.team_a_wins, r.team_b_wins)
            for r in session.execute(select(HistoricalResult)).scalars()]
    seen = set(session.execute(select(HistoricalResult.provider_id)).scalars())
    for f in session.execute(select(Fixture).where(Fixture.status == "COMPLETED")).scalars():
        if f.provider_id in seen or f.team_a_id is None or f.team_b_id is None:
            continue
        recs.append(SeriesRecord(f.scheduled_at, "worlds", f.team_a_id, f.team_b_id, f.team_a_wins, f.team_b_wins))
    recs.sort(key=lambda r: r.played_at)
    return [r for r in recs if until is None or r.played_at < until]


def priors(session: Session) -> dict[uuid.UUID, float]:
    return {t.id: REGION_PRIOR.get(t.region or "", DEFAULT_PRIOR) for t in session.execute(select(Team)).scalars()}


def fit(session: Session, until: datetime | None = None) -> EloModel:
    model = EloModel(priors=priors(session))
    for rec in load_records(session, until):
        model.update(rec)
    return model


@dataclass
class Backtest:
    series: int
    log_loss: float
    brier: float
    baseline_log_loss: float
    accuracy: float

    @property
    def beats_baseline(self) -> bool:
        return self.series >= 20 and self.log_loss < self.baseline_log_loss


def backtest(session: Session) -> Backtest:
    """Walk forward: predict each international series before learning from it."""
    model = EloModel(priors=priors(session))
    ll = br = base = correct = 0.0
    n = 0
    for rec in load_records(session):
        if rec.league in INTERNATIONAL:
            best_of = 2 * max(rec.a_wins, rec.b_wins) - 1
            if best_of in (1, 3, 5):
                p = min(max(series_win_probability(model.game_probability(rec.team_a, rec.team_b), best_of),
                            1e-4), 1 - 1e-4)
                y = 1.0 if rec.a_wins > rec.b_wins else 0.0
                ll -= y * math.log(p) + (1 - y) * math.log(1 - p)
                br += (p - y) ** 2
                base += math.log(2)
                correct += 1.0 if (p > 0.5) == (y == 1.0) else 0.0
                n += 1
        model.update(rec)
    if n == 0:
        return Backtest(0, 0.0, 0.0, 0.0, 0.0)
    return Backtest(n, ll / n, br / n, base / n, correct / n)


def persist(session: Session, model: EloModel) -> None:
    session.execute(delete(TeamRating))
    for team_id, rating in model.ratings.items():
        session.add(TeamRating(team_id=team_id, rating=round(rating, 2), games=model.games.get(team_id, 0),
                               model_key=MODEL_KEY))
    session.flush()
