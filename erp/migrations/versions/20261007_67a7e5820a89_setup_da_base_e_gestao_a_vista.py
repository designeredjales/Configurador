"""Setup da base (integração Promob Prices configurável) e gestão à vista (metas e WIP)

Revision ID: 67a7e5820a89
Revises: 20045c43f414
Create Date: 2026-10-07 16:15:39.405744

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67a7e5820a89'
down_revision: Union[str, Sequence[str], None] = '20045c43f414'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('config_gestao',
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('metas', sa.JSON(), nullable=True),
    sa.Column('limites_wip', sa.JSON(), nullable=True),
    sa.Column('dias_uteis_mes', sa.Integer(), nullable=False, server_default='22'),
    sa.Column('horas_turno', sa.Float(), nullable=False, server_default='8.8'),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('empresa_id')
    )
    with op.batch_alter_table('config_comercial', schema=None) as batch_op:
        batch_op.add_column(sa.Column('prices_url', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('prices_tabela_preferida', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('prices_colunas', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('config_comercial', schema=None) as batch_op:
        batch_op.drop_column('prices_colunas')
        batch_op.drop_column('prices_tabela_preferida')
        batch_op.drop_column('prices_url')

    op.drop_table('config_gestao')
