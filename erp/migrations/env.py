"""Ambiente do Alembic: usa o modelo do ERP e o DATABASE_URL da aplicação."""
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registra as tabelas no metadata)
from app.db import DATABASE_URL, Base, criar_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

URL = config.attributes.get("url") or DATABASE_URL
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def _migrar(conexao) -> None:
    # render_as_batch: permite ALTER TABLE também no SQLite (desenvolvimento)
    context.configure(connection=conexao, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    conexao = config.attributes.get("connection")  # testes passam a conexão pronta
    if conexao is not None:
        _migrar(conexao)
        return
    with criar_engine(URL).connect() as conexao:
        _migrar(conexao)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
