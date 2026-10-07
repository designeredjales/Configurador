"""De-para Promob → estoque, capacidade e custo-hora por setor, tambor e pulmão

Revision ID: e75a3a553adb
Revises: 67a7e5820a89
Create Date: 2026-10-07 18:12:41.602563

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e75a3a553adb'
down_revision: Union[str, Sequence[str], None] = '67a7e5820a89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('depara_materiais',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('codigo_promob', sa.String(length=60), nullable=False),
    sa.Column('material_id', sa.Integer(), nullable=False),
    sa.Column('fator', sa.Float(), nullable=False),
    sa.Column('observacao', sa.String(length=200), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.ForeignKeyConstraint(['material_id'], ['materiais.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'codigo_promob')
    )
    with op.batch_alter_table('depara_materiais', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_depara_materiais_empresa_id'), ['empresa_id'], unique=False)

    with op.batch_alter_table('centros_trabalho', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pessoas', sa.Float(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('horas_dia', sa.Float(), server_default='8.8', nullable=False))
        batch_op.add_column(sa.Column('eficiencia_pct', sa.Float(), server_default='85', nullable=False))
        batch_op.add_column(sa.Column('custo_mensal', sa.Float(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('minutos_peca', sa.Float(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('minutos_m2', sa.Float(), server_default='0', nullable=False))

    with op.batch_alter_table('config_gestao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pulmao_dias', sa.Float(), server_default='2', nullable=False))
        batch_op.add_column(sa.Column('tambor_codigo', sa.String(length=20), nullable=True))

    with op.batch_alter_table('empresas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('promob_cria_materiais', sa.Boolean(), server_default='1', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('empresas', schema=None) as batch_op:
        batch_op.drop_column('promob_cria_materiais')

    with op.batch_alter_table('config_gestao', schema=None) as batch_op:
        batch_op.drop_column('tambor_codigo')
        batch_op.drop_column('pulmao_dias')

    with op.batch_alter_table('centros_trabalho', schema=None) as batch_op:
        batch_op.drop_column('minutos_m2')
        batch_op.drop_column('minutos_peca')
        batch_op.drop_column('custo_mensal')
        batch_op.drop_column('eficiencia_pct')
        batch_op.drop_column('horas_dia')
        batch_op.drop_column('pessoas')

    with op.batch_alter_table('depara_materiais', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_depara_materiais_empresa_id'))

    op.drop_table('depara_materiais')
