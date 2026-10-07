"""lotes de producao e caixa master

Revision ID: f978421d4781
Revises: 8a7380b4b4ec
Create Date: 2026-10-07 11:55:07.790252

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f978421d4781'
down_revision: Union[str, Sequence[str], None] = '8a7380b4b4ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('lotes_producao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('descricao', sa.String(length=120), nullable=False),
    sa.Column('data_entrega', sa.Date(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('criado_por', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'numero')
    )
    with op.batch_alter_table('lotes_producao', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lotes_producao_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('caixas_master',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('codigo_barras', sa.String(length=20), nullable=False),
    sa.Column('projeto_id', sa.Integer(), nullable=False),
    sa.Column('ambiente_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('criado_por', sa.String(length=120), nullable=True),
    sa.Column('fechada_em', sa.DateTime(), nullable=True),
    sa.Column('expedida_em', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['ambiente_id'], ['ambientes.id'], ),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.ForeignKeyConstraint(['projeto_id'], ['projetos.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'numero')
    )
    with op.batch_alter_table('caixas_master', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_caixas_master_codigo_barras'), ['codigo_barras'], unique=True)
        batch_op.create_index(batch_op.f('ix_caixas_master_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_caixas_master_projeto_id'), ['projeto_id'], unique=False)

    op.create_table('itens_caixa',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('caixa_id', sa.Integer(), nullable=False),
    sa.Column('unidade_id', sa.Integer(), nullable=False),
    sa.Column('adicionado_em', sa.DateTime(), nullable=False),
    sa.Column('usuario_nome', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['caixa_id'], ['caixas_master.id'], ),
    sa.ForeignKeyConstraint(['unidade_id'], ['unidades_peca.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('unidade_id')
    )
    with op.batch_alter_table('itens_caixa', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_itens_caixa_caixa_id'), ['caixa_id'], unique=False)

    with op.batch_alter_table('empresas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('caixa_max_modulos', sa.Integer(), server_default='3', nullable=False))

    with op.batch_alter_table('ordens_producao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lote_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_ordens_producao_lote_id'), ['lote_id'], unique=False)
        batch_op.create_foreign_key('fk_ordens_producao_lote_id', 'lotes_producao', ['lote_id'], ['id'])



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ordens_producao', schema=None) as batch_op:
        batch_op.drop_constraint('fk_ordens_producao_lote_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_ordens_producao_lote_id'))
        batch_op.drop_column('lote_id')

    with op.batch_alter_table('empresas', schema=None) as batch_op:
        batch_op.drop_column('caixa_max_modulos')

    with op.batch_alter_table('itens_caixa', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_itens_caixa_caixa_id'))

    op.drop_table('itens_caixa')
    with op.batch_alter_table('caixas_master', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_caixas_master_projeto_id'))
        batch_op.drop_index(batch_op.f('ix_caixas_master_empresa_id'))
        batch_op.drop_index(batch_op.f('ix_caixas_master_codigo_barras'))

    op.drop_table('caixas_master')
    with op.batch_alter_table('lotes_producao', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lotes_producao_empresa_id'))

    op.drop_table('lotes_producao')
