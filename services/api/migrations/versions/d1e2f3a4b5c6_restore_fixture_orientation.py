"""Restore fixtures whose team order the schedule sync flipped after their markets were built.

The match winner's outcome A carries team A's name from when the market was created. Where it names the
fixture's current team B instead, swap the teams and wins back and mark the fixture changed, so the worker
regrades any market settled against the flipped order.
"""
import sqlalchemy as sa
from alembic import op

from rift.display import team_name

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = depends_on = None


def upgrade():
    db = op.get_bind()
    rows = db.execute(sa.text(
        "SELECT f.id, f.provider_id, o.label, ta.code, ta.name, tb.code, tb.name "
        "FROM fixtures f "
        "JOIN teams ta ON ta.id = f.team_a_id JOIN teams tb ON tb.id = f.team_b_id "
        "JOIN markets m ON m.fixture_id = f.id AND m.kind = 'series_winner' "
        "JOIN outcomes o ON o.market_id = m.id AND o.code = 'A'")).all()
    for fixture_id, provider_id, label, a_code, a_name, b_code, b_name in rows:
        if label in (b_name, team_name(b_code, b_name)) and label not in (a_name, team_name(a_code, a_name)):
            db.execute(sa.text(
                "UPDATE fixtures SET team_a_id = team_b_id, team_b_id = team_a_id, "
                "team_a_wins = team_b_wins, team_b_wins = team_a_wins, "
                "data_changed_at = now(), updated_at = now() WHERE id = :id"), {"id": fixture_id})
            print(f"restored team order on fixture {provider_id}")


def downgrade():
    pass  # the flipped order was the defect
