"""modulo comercial

Revision ID: 20045c43f414
Revises: 5f32b38213dd
Create Date: 2026-10-07 15:38:09.127474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20045c43f414'
down_revision: Union[str, Sequence[str], None] = '5f32b38213dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('config_comercial',
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('desconto_max_vendedor', sa.Float(), nullable=False),
    sa.Column('desconto_max_gerente', sa.Float(), nullable=False),
    sa.Column('margem_minima', sa.Float(), nullable=False),
    sa.Column('comissao_vendedor_pct', sa.Float(), nullable=False),
    sa.Column('limite_divergencia_pct', sa.Float(), nullable=False),
    sa.Column('validade_proposta_dias', sa.Integer(), nullable=False),
    sa.Column('etapas', sa.JSON(), nullable=True),
    sa.Column('condicoes', sa.JSON(), nullable=True),
    sa.Column('prices_token', sa.String(length=2000), nullable=True),
    sa.Column('prices_tabela', sa.String(length=200), nullable=True),
    sa.Column('prices_sincronizado_em', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('empresa_id')
    )
    op.create_table('parceiros',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=160), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('documento', sa.String(length=20), nullable=True),
    sa.Column('telefone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=160), nullable=True),
    sa.Column('rt_pct', sa.Float(), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('parceiros', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_parceiros_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('precos_promob',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=80), nullable=False),
    sa.Column('descricao', sa.String(length=300), nullable=False),
    sa.Column('preco', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('precos_promob', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_precos_promob_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_precos_promob_sku'), ['sku'], unique=False)

    op.create_table('oportunidades',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=160), nullable=False),
    sa.Column('cliente_nome', sa.String(length=160), nullable=False),
    sa.Column('telefone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=160), nullable=True),
    sa.Column('etapa', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('origem', sa.String(length=60), nullable=True),
    sa.Column('parceiro_id', sa.Integer(), nullable=True),
    sa.Column('vendedor_id', sa.Integer(), nullable=True),
    sa.Column('valor_estimado', sa.Float(), nullable=True),
    sa.Column('link_3d', sa.String(length=400), nullable=True),
    sa.Column('link_2020', sa.String(length=400), nullable=True),
    sa.Column('token_2020', sa.String(length=400), nullable=True),
    sa.Column('proxima_acao', sa.String(length=200), nullable=True),
    sa.Column('proxima_acao_em', sa.Date(), nullable=True),
    sa.Column('motivo_perda', sa.String(length=200), nullable=True),
    sa.Column('projeto_id', sa.Integer(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('fechado_em', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.ForeignKeyConstraint(['parceiro_id'], ['parceiros.id'], ),
    sa.ForeignKeyConstraint(['projeto_id'], ['projetos.id'], ),
    sa.ForeignKeyConstraint(['vendedor_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'numero')
    )
    with op.batch_alter_table('oportunidades', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_oportunidades_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('imagens_proposta',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('oportunidade_id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=200), nullable=False),
    sa.Column('tipo', sa.String(length=40), nullable=False),
    sa.Column('caminho', sa.String(length=300), nullable=False),
    sa.Column('legenda', sa.String(length=160), nullable=True),
    sa.ForeignKeyConstraint(['oportunidade_id'], ['oportunidades.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('imagens_proposta', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_imagens_proposta_oportunidade_id'), ['oportunidade_id'], unique=False)

    op.create_table('versoes_proposta',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('oportunidade_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('arquivo', sa.String(length=200), nullable=False),
    sa.Column('xml', sa.Text(), nullable=False),
    sa.Column('resumo', sa.JSON(), nullable=False),
    sa.Column('desconto_pct', sa.Float(), nullable=False),
    sa.Column('condicao', sa.String(length=60), nullable=True),
    sa.Column('calculo', sa.JSON(), nullable=True),
    sa.Column('aprovacao', sa.String(length=12), nullable=False),
    sa.Column('aprovacao_motivo', sa.String(length=300), nullable=True),
    sa.Column('aprovado_por', sa.String(length=120), nullable=True),
    sa.Column('token_publico', sa.String(length=64), nullable=True),
    sa.Column('proposta_validade', sa.Date(), nullable=True),
    sa.Column('aceite_em', sa.DateTime(), nullable=True),
    sa.Column('aceite_nome', sa.String(length=160), nullable=True),
    sa.Column('aceite_ip', sa.String(length=64), nullable=True),
    sa.Column('criado_por', sa.String(length=120), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['oportunidade_id'], ['oportunidades.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('versoes_proposta', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_versoes_proposta_oportunidade_id'), ['oportunidade_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_versoes_proposta_token_publico'), ['token_publico'], unique=True)

    with op.batch_alter_table('projetos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('oportunidade_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('venda_resumo', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('auditoria_ciente_por', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('auditoria_ciente_em', sa.DateTime(), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projetos', schema=None) as batch_op:
        batch_op.drop_column('auditoria_ciente_em')
        batch_op.drop_column('auditoria_ciente_por')
        batch_op.drop_column('venda_resumo')
        batch_op.drop_column('oportunidade_id')

    with op.batch_alter_table('versoes_proposta', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_versoes_proposta_token_publico'))
        batch_op.drop_index(batch_op.f('ix_versoes_proposta_oportunidade_id'))

    op.drop_table('versoes_proposta')
    with op.batch_alter_table('imagens_proposta', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_imagens_proposta_oportunidade_id'))

    op.drop_table('imagens_proposta')
    with op.batch_alter_table('oportunidades', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_oportunidades_empresa_id'))

    op.drop_table('oportunidades')
    with op.batch_alter_table('precos_promob', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_precos_promob_sku'))
        batch_op.drop_index(batch_op.f('ix_precos_promob_empresa_id'))

    op.drop_table('precos_promob')
    with op.batch_alter_table('parceiros', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_parceiros_empresa_id'))

    op.drop_table('parceiros')
    op.drop_table('config_comercial')
