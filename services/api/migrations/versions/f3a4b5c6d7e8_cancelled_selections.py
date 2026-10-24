"""A pick can be cancelled before its market locks (D-038): status CANCELLED, never settled."""
import sqlalchemy as sa
from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = depends_on = None


def upgrade():
    op.alter_column("selections", "status", type_=sa.String(length=12), existing_type=sa.String(length=8))
    op.drop_constraint("ck_selection_status", "selections", type_="check")
    op.create_check_constraint("ck_selection_status", "selections",
                               "status IN ('OPEN','WON','PARTIAL','LOST','VOID','CANCELLED')")


def downgrade():
    op.drop_constraint("ck_selection_status", "selections", type_="check")
    op.create_check_constraint("ck_selection_status", "selections", "status IN ('OPEN','WON','PARTIAL','LOST','VOID')")
    op.alter_column("selections", "status", type_=sa.String(length=8), existing_type=sa.String(length=12))
