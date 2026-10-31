from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import Base


def build_engine(url: str, *, echo: bool = False):
    if make_url(url).get_backend_name() != "sqlite":
        raise ValueError("This assignment supports SQLite; see DESIGN.md for porting notes")
    engine = create_engine(url, echo=echo, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def initialize_database(engine):
    database = engine.url.database
    if database and database != ":memory:":
        Path(database).resolve().parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    # Database triggers also protect against bulk SQL bypassing ORM listeners.
    with engine.begin() as connection:
        for action in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS ledger_no_{action.lower()} "
                f"BEFORE {action} ON ledger_entries BEGIN "
                "SELECT RAISE(ABORT, 'Ledger entries are append-only'); END"
            )


settings = get_settings()
engine = build_engine(settings.database_url, echo=settings.sql_echo)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
