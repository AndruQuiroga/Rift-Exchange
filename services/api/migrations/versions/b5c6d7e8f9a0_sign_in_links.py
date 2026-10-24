"""Admin-issued, revocable permanent login links."""
import sqlalchemy as sa
from alembic import op

revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "sign_in_links",
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("sign_in_links")
