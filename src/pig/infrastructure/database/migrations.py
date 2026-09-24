from __future__ import annotations

from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL


def alembic_config(database_path: Path) -> Config:
    root = _distribution_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    url = URL.create("sqlite+pysqlite", database=str(database_path.resolve(strict=False)))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    return config


def _distribution_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve(strict=True)
    return Path(__file__).resolve().parents[4]


def upgrade_database(database_path: Path, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_path), revision)


def downgrade_database(database_path: Path, revision: str = "base") -> None:
    command.downgrade(alembic_config(database_path), revision)
