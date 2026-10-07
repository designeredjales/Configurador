"""auditoria e registro de erros

Revision ID: 5f32b38213dd
Revises: fc5cdbdace65
Create Date: 2026-10-07 14:18:28.889437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f32b38213dd'
down_revision: Union[str, Sequence[str], None] = 'fc5cdbdace65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('erros_sistema',
    sa.Column('id', sa.String(length=12), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('quando', sa.DateTime(), nullable=False),
    sa.Column('metodo', sa.String(length=8), nullable=False),
    sa.Column('rota', sa.String(length=200), nullable=False),
    sa.Column('tipo', sa.String(length=120), nullable=False),
    sa.Column('mensagem', sa.String(length=500), nullable=False),
    sa.Column('rastreio', sa.String(length=8000), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('erros_sistema', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_erros_sistema_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_erros_sistema_quando'), ['quando'], unique=False)

    op.create_table('auditoria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('usuario_nome', sa.String(length=120), nullable=True),
    sa.Column('quando', sa.DateTime(), nullable=False),
    sa.Column('metodo', sa.String(length=8), nullable=False),
    sa.Column('rota', sa.String(length=200), nullable=False),
    sa.Column('acao', sa.String(length=160), nullable=False),
    sa.Column('entidade_id', sa.String(length=40), nullable=True),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('detalhes', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('auditoria', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auditoria_empresa_id'), ['empresa_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_auditoria_quando'), ['quando'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('auditoria', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auditoria_quando'))
        batch_op.drop_index(batch_op.f('ix_auditoria_empresa_id'))

    op.drop_table('auditoria')
    with op.batch_alter_table('erros_sistema', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_erros_sistema_quando'))
        batch_op.drop_index(batch_op.f('ix_erros_sistema_empresa_id'))

    op.drop_table('erros_sistema')
