"""motivo de cancelamento da OP

Revision ID: a10fcdd8bd93
Revises: f978421d4781
Create Date: 2026-10-07 12:58:23.803268

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a10fcdd8bd93'
down_revision: Union[str, Sequence[str], None] = 'f978421d4781'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('ordens_producao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('motivo_cancelamento', sa.String(length=200), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ordens_producao', schema=None) as batch_op:
        batch_op.drop_column('motivo_cancelamento')

