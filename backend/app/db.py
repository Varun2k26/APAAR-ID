"""Database engine + session.

SQLite is the default (zero setup). Every SQLite transaction starts with BEGIN IMMEDIATE so
writers are serialised up front; that removes the 'read snapshot then fail to upgrade'
class of SQLite errors and makes the concurrent-submission guarantee hold. On Postgres the
partial unique index alone guarantees that only one active regular enrolment wins.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    is_sqlite = url.startswith("sqlite")
    kwargs = {"future": True}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 60}
    eng = create_engine(url, **kwargs)
    if is_sqlite:
        @event.listens_for(eng, "connect")
        def _on_connect(dbapi_conn, _rec):
            dbapi_conn.isolation_level = None          # we emit BEGIN ourselves
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        @event.listens_for(eng, "begin")
        def _on_begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")
    return eng


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"
