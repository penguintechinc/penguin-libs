"""Tests for penguin_pytest.dal fixtures."""

from __future__ import annotations

from sqlalchemy import Engine, text


def test_sqlite_engine_is_engine(sqlite_engine: Engine) -> None:
    assert sqlite_engine is not None
    with sqlite_engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.fetchone() == (1,)


def test_users_posts_engine_has_users_table(users_posts_engine: Engine) -> None:
    with users_posts_engine.connect() as conn:
        rows = conn.execute(text("SELECT email FROM users ORDER BY id")).fetchall()
    emails = [r[0] for r in rows]
    assert "alice@example.com" in emails
    assert "bob@example.com" in emails


def test_users_posts_engine_has_posts_table(users_posts_engine: Engine) -> None:
    with users_posts_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM posts")).scalar()
    assert count == 3


def test_dal_db_reflects_metadata(dal_db: object) -> None:
    from sqlalchemy import MetaData

    assert isinstance(dal_db._metadata, MetaData)
    assert "users" in dal_db._metadata.tables
    assert "posts" in dal_db._metadata.tables
