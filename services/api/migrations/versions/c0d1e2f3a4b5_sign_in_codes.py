"""One-time sign-in codes for adding a device to an existing account."""
import sqlalchemy as sa
from alembic import op

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "sign_in_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("code_hash"),
    )
    op.create_index(op.f("ix_sign_in_codes_user_id"), "sign_in_codes", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_sign_in_codes_user_id"), table_name="sign_in_codes")
    op.drop_table("sign_in_codes")
