"""funcoes por usuario e controle de producao

Revision ID: 8a7380b4b4ec
Revises: 6c4bd1858229
Create Date: 2026-10-07 04:47:10.796235

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a7380b4b4ec'
down_revision: Union[str, Sequence[str], None] = '6c4bd1858229'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ocorrencias_producao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('op_id', sa.Integer(), nullable=False),
    sa.Column('unidade_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=10), nullable=False),
    sa.Column('centro_codigo', sa.String(length=20), nullable=False),
    sa.Column('motivo', sa.String(length=300), nullable=False),
    sa.Column('custo_material', sa.Float(), nullable=False),
    sa.Column('nova_unidade_id', sa.Integer(), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('usuario_nome', sa.String(length=120), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.ForeignKeyConstraint(['nova_unidade_id'], ['unidades_peca.id'], ),
    sa.ForeignKeyConstraint(['op_id'], ['ordens_producao.id'], ),
    sa.ForeignKeyConstraint(['unidade_id'], ['unidades_peca.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ocorrencias_producao', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ocorrencias_producao_criado_em'), ['criado_em'], unique=False)
        batch_op.create_index(batch_op.f('ix_ocorrencias_producao_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ocorrencias_producao_op_id'), ['op_id'], unique=False)

    with op.batch_alter_table('unidades_peca', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=10), nullable=False, server_default='ATIVA'))  # peças existentes seguem ativas
        batch_op.add_column(sa.Column('reposicao_de_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_unidades_peca_reposicao_de_id', 'unidades_peca', ['reposicao_de_id'], ['id'])

    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('funcoes', sa.JSON(), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('funcoes')

    with op.batch_alter_table('unidades_peca', schema=None) as batch_op:
        batch_op.drop_constraint('fk_unidades_peca_reposicao_de_id', type_='foreignkey')
        batch_op.drop_column('reposicao_de_id')
        batch_op.drop_column('status')

    with op.batch_alter_table('ocorrencias_producao', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ocorrencias_producao_op_id'))
        batch_op.drop_index(batch_op.f('ix_ocorrencias_producao_empresa_id'))
        batch_op.drop_index(batch_op.f('ix_ocorrencias_producao_criado_em'))

    op.drop_table('ocorrencias_producao')
