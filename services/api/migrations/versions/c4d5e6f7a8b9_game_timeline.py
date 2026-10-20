"""games carry a livestats timeline (start/end, objective firsts, dragons, 15-minute and final lines)

Revision ID: c4d5e6f7a8b9
Revises: b3a1d2c4e5f6
Create Date: 2026-10-20 23:59:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3a1d2c4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('games', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('games', sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('games', sa.Column('timeline', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('games', sa.Column('timeline_complete', sa.Boolean(), server_default=sa.false(),
                                     nullable=False))


def downgrade() -> None:
    op.drop_column('games', 'timeline_complete')
    op.drop_column('games', 'timeline')
    op.drop_column('games', 'ended_at')
    op.drop_column('games', 'started_at')
