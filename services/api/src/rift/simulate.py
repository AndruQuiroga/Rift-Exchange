"""Monte Carlo of the remaining Worlds bracket for futures pricing (EXPERIMENTAL).

Swiss: completed results are fixed; currently drawn fixtures are simulated as scheduled; later rounds pair
teams on equal records at random (avoiding rematches where possible). Bo3 when a team can advance or be
eliminated, otherwise Bo1 (Worlds 2026 primer). Knockouts: known pairings are used, otherwise a random
bracket of the eight qualifiers; all Bo5.
"""

import random
import uuid
from collections import Counter
from dataclasses import dataclass

from rift.domain.pricing import series_win_probability
from rift.models import Fixture
from rift.ratings import EloModel

KNOCKOUT_STAGES = ("Quarterfinals", "Semifinals", "Finals")


@dataclass
class FuturesProbabilities:
    advance: dict[uuid.UUID, float]
    champion: dict[uuid.UUID, float]
    sims: int


def simulate(fixtures: list[Fixture], model: EloModel, sims: int = 4000, seed: int = 2026) -> FuturesProbabilities | None:
    swiss = [f for f in fixtures if f.stage == "Swiss"]
    teams = sorted({t for f in swiss for t in (f.team_a_id, f.team_b_id) if t})
    if len(teams) != 16:
        return None
    rng = random.Random(seed)
    win_cache: dict[tuple[uuid.UUID, uuid.UUID, int], float] = {}

    def p_series(a, b, bo):
        key = (a, b, bo)
        if key not in win_cache:
            win_cache[key] = series_win_probability(model.game_probability(a, b), bo)
        return win_cache[key]

    def play(a, b, bo):
        return a if rng.random() < p_series(a, b, bo) else b

    done_swiss = [f for f in swiss if f.status == "COMPLETED" and f.winner_team_id and f.team_a_id and f.team_b_id]
    pending_swiss = sorted((f for f in swiss if f.status != "COMPLETED" and f.team_a_id and f.team_b_id),
                           key=lambda f: f.scheduled_at)
    ko = [f for f in fixtures if f.stage in KNOCKOUT_STAGES]
    qf_known = [(f.team_a_id, f.team_b_id) for f in sorted(ko, key=lambda f: f.scheduled_at)
                if f.stage == "Quarterfinals" and f.team_a_id and f.team_b_id]
    ko_results = {(f.team_a_id, f.team_b_id): f.winner_team_id for f in ko if f.status == "COMPLETED"}

    adv, champ = Counter(), Counter()
    for _ in range(sims):
        wins = dict.fromkeys(teams, 0)
        losses = dict.fromkeys(teams, 0)
        met: set[frozenset] = set()

        def record(a, b, w, wins=wins, losses=losses, met=met):
            wins[w] += 1
            losses[b if w == a else a] += 1
            met.add(frozenset((a, b)))

        for f in done_swiss:
            record(f.team_a_id, f.team_b_id, f.winner_team_id)
        for f in pending_swiss:
            a, b = f.team_a_id, f.team_b_id
            if wins[a] < 3 and losses[a] < 3 and wins[b] < 3 and losses[b] < 3:
                record(a, b, play(a, b, f.best_of))
        for _round in range(6):
            active = [t for t in teams if wins[t] < 3 and losses[t] < 3]
            if not active:
                break
            groups: dict[tuple[int, int], list] = {}
            for t in active:
                groups.setdefault((wins[t], losses[t]), []).append(t)
            for (w, losses_at), group in groups.items():
                rng.shuffle(group)
                while len(group) >= 2:
                    a = group.pop()
                    idx = next((i for i, b in enumerate(group) if frozenset((a, b)) not in met), 0)
                    b = group.pop(idx)
                    bo = 3 if w == 2 or losses_at == 2 else 1
                    record(a, b, play(a, b, bo))
        qualified = [t for t in teams if wins[t] >= 3]
        for t in qualified:
            adv[t] += 1
        if len(qualified) != 8:
            continue
        if len(qf_known) == 4:
            pairs = qf_known
        else:
            bracket = qualified[:]
            rng.shuffle(bracket)
            pairs = [(bracket[i], bracket[i + 1]) for i in range(0, 8, 2)]
        alive = [ko_results.get(p) or play(p[0], p[1], 5) for p in pairs]
        while len(alive) > 1:
            alive = [ko_results.get((alive[i], alive[i + 1])) or play(alive[i], alive[i + 1], 5)
                     for i in range(0, len(alive), 2)]
        champ[alive[0]] += 1
    return FuturesProbabilities(
        advance={t: adv[t] / sims for t in teams},
        champion={t: champ[t] / sims for t in teams},
        sims=sims,
    )
