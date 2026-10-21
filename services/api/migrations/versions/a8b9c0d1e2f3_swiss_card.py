"""Free Swiss record card: one call per team, no stake, a capped RC reward (ledger kind REWARD)."""
import sqlalchemy as sa
from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = depends_on = None

KINDS = "'GRANT_OPENING','GRANT_MATCH_DAY','STAKE','PAYOUT','VOID_REFUND','REVERSAL'"


def upgrade():
    op.create_table(
        "swiss_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("market_id", sa.UUID(), nullable=False),
        sa.Column("outcome_id", sa.UUID(), nullable=False),
        sa.Column("odds", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("odds_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("reward_rc", sa.BigInteger(), nullable=False),
        sa.Column("settled_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("odds > 1", name="ck_swiss_call_odds"),
        sa.CheckConstraint("status IN ('OPEN','WON','PARTIAL','LOST','VOID')", name="ck_swiss_call_status"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.ForeignKeyConstraint(["outcome_id"], ["outcomes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "market_id", name="uq_swiss_call_market"),
    )
    op.create_index(op.f("ix_swiss_calls_market_id"), "swiss_calls", ["market_id"], unique=False)
    op.create_index(op.f("ix_swiss_calls_user_id"), "swiss_calls", ["user_id"], unique=False)
    op.drop_constraint("ck_ledger_kind", "ledger_entries", type_="check")
    op.create_check_constraint("ck_ledger_kind", "ledger_entries", f"kind IN ({KINDS},'REWARD')")


def downgrade():
    op.drop_constraint("ck_ledger_kind", "ledger_entries", type_="check")
    op.create_check_constraint("ck_ledger_kind", "ledger_entries", f"kind IN ({KINDS})")
    op.drop_index(op.f("ix_swiss_calls_user_id"), table_name="swiss_calls")
    op.drop_index(op.f("ix_swiss_calls_market_id"), table_name="swiss_calls")
    op.drop_table("swiss_calls")
