"""Opening grant 1,000 -> 5,000 RC (D-022). The worker tops up members who joined at the old amount."""
import sqlalchemy as sa
from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = depends_on = None


def upgrade():
    db = op.get_bind()
    rows = db.execute(sa.text("UPDATE seasons SET opening_grant_rc = 5000 WHERE opening_grant_rc < 5000 "
                              "RETURNING id")).scalars().all()
    for season_id in rows:  # economy changes are visible to every member (docs/spec/16 change control)
        db.execute(sa.text("INSERT INTO audit_events (actor, action, entity_type, entity_id, data) "
                           "VALUES ('migration', 'season.opening_grant_raised', 'season', :id, "
                           "CAST(:data AS JSONB))"), {"id": str(season_id), "data": '{"from": 1000, "to": 5000}'})


def downgrade():
    pass  # top-ups already paid stay in the ledger; lowering the grant later would not claw them back
