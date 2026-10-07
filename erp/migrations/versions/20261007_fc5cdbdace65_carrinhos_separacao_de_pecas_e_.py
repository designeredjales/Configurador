"""carrinhos, separacao de pecas e conferencia por setor

Revision ID: fc5cdbdace65
Revises: a10fcdd8bd93
Create Date: 2026-10-07 13:17:59.764420

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc5cdbdace65'
down_revision: Union[str, Sequence[str], None] = 'a10fcdd8bd93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('carrinhos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('codigo_barras', sa.String(length=20), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'numero')
    )
    with op.batch_alter_table('carrinhos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_carrinhos_codigo_barras'), ['codigo_barras'], unique=True)
        batch_op.create_index(batch_op.f('ix_carrinhos_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('classes_separacao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=20), nullable=False),
    sa.Column('nome', sa.String(length=60), nullable=False),
    sa.Column('palavras_chave', sa.String(length=400), nullable=False),
    sa.Column('centro_codigo', sa.String(length=20), nullable=True),
    sa.Column('vai_para_caixa', sa.Boolean(), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'codigo')
    )
    with op.batch_alter_table('classes_separacao', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_classes_separacao_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('itens_carrinho',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('carrinho_id', sa.Integer(), nullable=False),
    sa.Column('unidade_id', sa.Integer(), nullable=False),
    sa.Column('centro_codigo', sa.String(length=20), nullable=False),
    sa.Column('adicionado_em', sa.DateTime(), nullable=False),
    sa.Column('usuario_nome', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['carrinho_id'], ['carrinhos.id'], ),
    sa.ForeignKeyConstraint(['unidade_id'], ['unidades_peca.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('unidade_id')
    )
    with op.batch_alter_table('itens_carrinho', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_itens_carrinho_carrinho_id'), ['carrinho_id'], unique=False)

    with op.batch_alter_table('centros_trabalho', schema=None) as batch_op:
        batch_op.add_column(sa.Column('exige_apontamento', sa.Boolean(), server_default='1', nullable=False))

    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('separacao', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('separacao_manual', sa.Boolean(), server_default='0', nullable=False))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.drop_column('separacao_manual')
        batch_op.drop_column('separacao')

    with op.batch_alter_table('centros_trabalho', schema=None) as batch_op:
        batch_op.drop_column('exige_apontamento')

    with op.batch_alter_table('itens_carrinho', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_itens_carrinho_carrinho_id'))

    op.drop_table('itens_carrinho')
    with op.batch_alter_table('classes_separacao', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_classes_separacao_empresa_id'))

    op.drop_table('classes_separacao')
    with op.batch_alter_table('carrinhos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_carrinhos_empresa_id'))
        batch_op.drop_index(batch_op.f('ix_carrinhos_codigo_barras'))

    op.drop_table('carrinhos')
