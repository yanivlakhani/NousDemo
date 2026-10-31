from sqlalchemy import Integer, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app import database


class BaseForTest(DeclarativeBase):
    pass


class Item(BaseForTest):
    __tablename__ = "read_scope_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


def test_read_session_scope_reads_without_committing(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    BaseForTest.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(Item.__table__.insert().values(id=1))
    monkeypatch.setattr(database, "get_read_engine", lambda: engine.execution_options(isolation_level="AUTOCOMMIT"))

    with database.read_session_scope() as session:
        assert session.scalar(select(Item.id)) == 1


def test_read_session_scope_rejects_pending_writes(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    BaseForTest.metadata.create_all(engine)
    monkeypatch.setattr(database, "get_read_engine", lambda: engine.execution_options(isolation_level="AUTOCOMMIT"))

    try:
        with database.read_session_scope() as session:
            session.add(Item(id=2))
    except RuntimeError as error:
        assert str(error) == "read_session_scope cannot persist changes"
    else:
        raise AssertionError("pending writes must be rejected")

    with engine.connect() as connection:
        assert connection.scalar(select(Item.id)) is None
