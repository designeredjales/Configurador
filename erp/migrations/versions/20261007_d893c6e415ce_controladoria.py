"""Controladoria: centros de custo, verbas, aprovação de despesas, cenários e consolidação do DRE gerencial

Revision ID: d893c6e415ce
Revises: e75a3a553adb
Create Date: 2026-10-07 18:29:13.436007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd893c6e415ce'
down_revision: Union[str, Sequence[str], None] = 'e75a3a553adb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('cenarios_planejamento',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('premissas', sa.JSON(), nullable=False),
    sa.Column('principal', sa.Boolean(), nullable=False),
    sa.Column('criado_por', sa.String(length=120), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('cenarios_planejamento', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cenarios_planejamento_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('config_financeira',
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('alcada_valor', sa.Float(), nullable=True),
    sa.Column('exige_centro', sa.Boolean(), nullable=False),
    sa.Column('bloqueia_sem_verba', sa.Boolean(), nullable=False),
    sa.Column('centros_padrao', sa.JSON(), nullable=True),
    sa.Column('consolidacao_ativa', sa.Boolean(), nullable=False, server_default='1'),
    sa.Column('consolidacao_hora', sa.Integer(), nullable=False),
    sa.Column('consolidacao_meses', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('empresa_id')
    )
    op.create_table('execucoes_consolidacao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('chave', sa.String(length=40), nullable=False),
    sa.Column('origem', sa.String(length=10), nullable=False),
    sa.Column('iniciado_em', sa.DateTime(), nullable=False),
    sa.Column('concluido_em', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('usuario', sa.String(length=120), nullable=True),
    sa.Column('resumo', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'chave')
    )
    with op.batch_alter_table('execucoes_consolidacao', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_execucoes_consolidacao_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('centros_custo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=20), nullable=False),
    sa.Column('nome', sa.String(length=100), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('responsavel_id', sa.Integer(), nullable=True),
    sa.Column('setor_codigo', sa.String(length=20), nullable=True),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.ForeignKeyConstraint(['responsavel_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'codigo')
    )
    with op.batch_alter_table('centros_custo', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_centros_custo_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('consolidacao_dre',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('ano', sa.Integer(), nullable=False),
    sa.Column('mes', sa.Integer(), nullable=False),
    sa.Column('regime', sa.String(length=12), nullable=False),
    sa.Column('centro_custo_id', sa.Integer(), nullable=True),
    sa.Column('conta', sa.String(length=30), nullable=False),
    sa.Column('valor', sa.Float(), nullable=False),
    sa.Column('fonte', sa.String(length=10), nullable=False),
    sa.Column('gerado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['centro_custo_id'], ['centros_custo.id'], ),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('consolidacao_dre', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_consolidacao_dre_ano'), ['ano'], unique=False)
        batch_op.create_index(batch_op.f('ix_consolidacao_dre_empresa_id'), ['empresa_id'], unique=False)

    op.create_table('verbas_centro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('centro_custo_id', sa.Integer(), nullable=False),
    sa.Column('ano', sa.Integer(), nullable=False),
    sa.Column('mes', sa.Integer(), nullable=False),
    sa.Column('conta', sa.String(length=30), nullable=False),
    sa.Column('valor', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['centro_custo_id'], ['centros_custo.id'], ),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('empresa_id', 'centro_custo_id', 'ano', 'mes', 'conta')
    )
    with op.batch_alter_table('verbas_centro', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_verbas_centro_centro_custo_id'), ['centro_custo_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_verbas_centro_empresa_id'), ['empresa_id'], unique=False)

    with op.batch_alter_table('lancamentos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('centro_custo_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('conta', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('aprovacao', sa.String(length=10), server_default='LIVRE', nullable=False))
        batch_op.add_column(sa.Column('aprovacao_motivo', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('aprovado_por', sa.String(length=120), nullable=True))
        batch_op.create_index(batch_op.f('ix_lancamentos_centro_custo_id'), ['centro_custo_id'], unique=False)
        batch_op.create_foreign_key('fk_lancamentos_centro_custo', 'centros_custo', ['centro_custo_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('lancamentos', schema=None) as batch_op:
        # WARNING: constraint name is None; this directive will fail as
        # rendered.  Add a name, or use a naming convention; see
        # https://alembic.sqlalchemy.org/en/latest/naming.html
        batch_op.drop_constraint('fk_lancamentos_centro_custo', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_lancamentos_centro_custo_id'))
        batch_op.drop_column('aprovado_por')
        batch_op.drop_column('aprovacao_motivo')
        batch_op.drop_column('aprovacao')
        batch_op.drop_column('conta')
        batch_op.drop_column('centro_custo_id')

    with op.batch_alter_table('verbas_centro', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_verbas_centro_empresa_id'))
        batch_op.drop_index(batch_op.f('ix_verbas_centro_centro_custo_id'))

    op.drop_table('verbas_centro')
    with op.batch_alter_table('consolidacao_dre', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_consolidacao_dre_empresa_id'))
        batch_op.drop_index(batch_op.f('ix_consolidacao_dre_ano'))

    op.drop_table('consolidacao_dre')
    with op.batch_alter_table('centros_custo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_centros_custo_empresa_id'))

    op.drop_table('centros_custo')
    with op.batch_alter_table('execucoes_consolidacao', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_execucoes_consolidacao_empresa_id'))

    op.drop_table('execucoes_consolidacao')
    op.drop_table('config_financeira')
    with op.batch_alter_table('cenarios_planejamento', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cenarios_planejamento_empresa_id'))

    op.drop_table('cenarios_planejamento')
