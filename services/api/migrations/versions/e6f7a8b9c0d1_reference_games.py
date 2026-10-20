"""Isolated reference games, never wager fixtures."""
from alembic import op
import sqlalchemy as sa

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = depends_on = None


def upgrade():
    op.create_table("reference_games",
        sa.Column("provider_id", sa.String(64), primary_key=True),
        sa.Column("event", sa.String(128), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("reference_games")
