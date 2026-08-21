"""Tests for DB.transaction() multi-statement raw-SQL context manager."""

import pytest

from penguin_dal import DB


@pytest.fixture
def db(tmp_path):
    d = DB(f"sqlite:///{tmp_path / 't.db'}", pool_size=1, reflect=False)
    d.executesql("CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT)")
    return d


def test_transaction_commits_on_clean_exit(db):
    with db.transaction() as tx:
        tx.executesql("INSERT INTO widget (name) VALUES (?)", ("a",))
        tx.executesql("INSERT INTO widget (name) VALUES (?)", ("b",))
    assert db.executesql("SELECT count(*) FROM widget") == [(2,)]


def test_transaction_rolls_back_on_exception(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as tx:
            tx.executesql("INSERT INTO widget (name) VALUES (?)", ("a",))
            raise RuntimeError("boom")
    assert db.executesql("SELECT count(*) FROM widget") == [(0,)]


def test_transaction_statements_share_one_connection(db):
    with db.transaction() as tx:
        tx.executesql("CREATE TEMPORARY TABLE t (x INTEGER)")
        tx.executesql("INSERT INTO t VALUES (1)")
        assert tx.executesql("SELECT x FROM t") == [(1,)]
