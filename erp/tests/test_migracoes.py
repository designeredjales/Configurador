"""As migrações do Alembic criam exatamente o schema do modelo (nada esquecido)."""
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import Base

RAIZ = Path(__file__).resolve().parents[1]


def test_migracoes_reproduzem_o_modelo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migrado.db'}")
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, "head")
    assert set(inspect(engine).get_table_names()) >= set(Base.metadata.tables)
    with engine.connect() as conexao:
        diferencas = compare_metadata(MigrationContext.configure(conexao, opts={"render_as_batch": True}), Base.metadata)
    assert diferencas == [], f"Modelo mudou sem migração: rode 'alembic revision --autogenerate'. {diferencas}"
