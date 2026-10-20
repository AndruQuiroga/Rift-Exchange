"""selections may settle PARTIAL (Swiss record consolation)

Revision ID: b3a1d2c4e5f6
Revises: e67c2bc534e2
Create Date: 2026-10-20 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b3a1d2c4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e67c2bc534e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_selection_status', 'selections', type_='check')
    op.create_check_constraint('ck_selection_status', 'selections',
                               "status IN ('OPEN','WON','PARTIAL','LOST','VOID')")


def downgrade() -> None:
    op.drop_constraint('ck_selection_status', 'selections', type_='check')
    op.create_check_constraint('ck_selection_status', 'selections', "status IN ('OPEN','WON','LOST','VOID')")
