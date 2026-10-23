"""Fixed-phrase reactions to friends' locked picks (D-034)."""
import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "reactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("season_id", sa.UUID(), nullable=False),
        sa.Column("fixture_id", sa.UUID(), nullable=True),
        sa.Column("selection_id", sa.UUID(), nullable=False),
        sa.Column("from_user_id", sa.UUID(), nullable=False),
        sa.Column("to_user_id", sa.UUID(), nullable=False),
        sa.Column("phrase", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"]),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["selection_id"], ["selections.id"]),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("selection_id", "from_user_id", "phrase", name="uq_reaction_once"),
    )
    op.create_index(op.f("ix_reactions_fixture_id"), "reactions", ["fixture_id"], unique=False)
    op.create_index(op.f("ix_reactions_selection_id"), "reactions", ["selection_id"], unique=False)
    op.create_index(op.f("ix_reactions_to_user_id"), "reactions", ["to_user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_reactions_to_user_id"), table_name="reactions")
    op.drop_index(op.f("ix_reactions_selection_id"), table_name="reactions")
    op.drop_index(op.f("ix_reactions_fixture_id"), table_name="reactions")
    op.drop_table("reactions")
