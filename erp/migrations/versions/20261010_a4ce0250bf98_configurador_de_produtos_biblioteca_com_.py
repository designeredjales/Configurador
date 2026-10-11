"""Configurador de produtos: biblioteca com herança, acabamentos, constantes e configurações geradas

Revision ID: a4ce0250bf98
Revises: d893c6e415ce
Create Date: 2026-10-10 23:59:15.211289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4ce0250bf98'
down_revision: Union[str, Sequence[str], None] = 'd893c6e415ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('acabamentos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=40), nullable=False),
    sa.Column('nome', sa.String(length=160), nullable=False),
    sa.Column('componentes', sa.JSON(), nullable=False),
    sa.Column('opcoes', sa.JSON(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'codigo')
    )
    with op.batch_alter_table('acabamentos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_acabamentos_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('config_produto',
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('constantes', sa.JSON(), nullable=True),
    sa.Column('perda_perfil_pct', sa.Float(), nullable=False),
    sa.Column('serra_perfil_mm', sa.Float(), nullable=False),
    sa.Column('markup_padrao', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('empresa_id')
    )
    op.create_table('produtos_nos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('pai_id', sa.Integer(), nullable=True),
    sa.Column('tipo', sa.String(length=12), nullable=False),
    sa.Column('codigo', sa.String(length=40), nullable=False),
    sa.Column('nome', sa.String(length=160), nullable=False),
    sa.Column('ordem', sa.Integer(), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('descricao_formula', sa.String(length=400), nullable=True),
    sa.Column('perguntas', sa.JSON(), nullable=True),
    sa.Column('componentes', sa.JSON(), nullable=True),
    sa.Column('preco', sa.JSON(), nullable=True),
    sa.Column('observacao', sa.String(length=400), nullable=True),
    sa.Column('atualizado_por', sa.String(length=120), nullable=True),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.ForeignKeyConstraint(['pai_id'], ['produtos_nos.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'codigo')
    )
    with op.batch_alter_table('produtos_nos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_produtos_nos_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_produtos_nos_pai_id'), ['pai_id'], unique=False)

    op.create_table('configuracoes_produto',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('modelo_id', sa.Integer(), nullable=False),
    sa.Column('sequencial', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=60), nullable=False),
    sa.Column('assinatura', sa.String(length=64), nullable=False),
    sa.Column('respostas', sa.JSON(), nullable=False),
    sa.Column('descricao', sa.String(length=300), nullable=False),
    sa.Column('modulo', sa.JSON(), nullable=False),
    sa.Column('custo', sa.JSON(), nullable=False),
    sa.Column('criado_por', sa.String(length=120), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.ForeignKeyConstraint(['modelo_id'], ['produtos_nos.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'codigo'),
    sa.UniqueConstraint('empresa_id', 'modelo_id', 'assinatura')
    )
    with op.batch_alter_table('configuracoes_produto', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_configuracoes_produto_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_configuracoes_produto_modelo_id'), ['modelo_id'], unique=False)

    with op.batch_alter_table('modulos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('configuracao_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_modulos_configuracao', 'configuracoes_produto', ['configuracao_id'], ['id'])

    with op.batch_alter_table('versoes_proposta', schema=None) as batch_op:
        batch_op.add_column(sa.Column('itens_config', sa.JSON(), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('versoes_proposta', schema=None) as batch_op:
        batch_op.drop_column('itens_config')

    with op.batch_alter_table('modulos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_modulos_configuracao', type_='foreignkey')
        batch_op.drop_column('configuracao_id')

    with op.batch_alter_table('configuracoes_produto', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_configuracoes_produto_modelo_id'))
        batch_op.drop_index(batch_op.f('ix_configuracoes_produto_empresa_id'))

    op.drop_table('configuracoes_produto')
    with op.batch_alter_table('produtos_nos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_produtos_nos_pai_id'))
        batch_op.drop_index(batch_op.f('ix_produtos_nos_empresa_id'))

    op.drop_table('produtos_nos')
    op.drop_table('config_produto')
    with op.batch_alter_table('acabamentos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_acabamentos_empresa_id'))

    op.drop_table('acabamentos')
