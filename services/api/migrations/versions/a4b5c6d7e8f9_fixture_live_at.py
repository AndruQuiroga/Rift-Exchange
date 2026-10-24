"""When a series went live: starts the countdown to its draft (D-039)."""
import sqlalchemy as sa
from alembic import op

revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = depends_on = None


def upgrade():
    op.add_column("fixtures", sa.Column("live_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("fixtures", "live_at")
