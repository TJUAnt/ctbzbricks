"""Tests for cross-dialect import upserts."""

import unittest
from unittest.mock import Mock

from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects import mysql, postgresql

from src.resource.db.upsert import upsert_statement


class UpsertStatementTest(unittest.TestCase):
    def setUp(self) -> None:
        metadata = MetaData()
        self.table = Table(
            "items",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String(64), nullable=False),
        )

    def session_for(self, dialect):
        bind = Mock()
        bind.dialect = dialect
        session = Mock()
        session.get_bind.return_value = bind
        return session

    def test_builds_postgresql_on_conflict_statement(self) -> None:
        statement = upsert_statement(
            self.session_for(postgresql.dialect()),
            self.table,
            [{"id": 1, "name": "brick"}],
            conflict_columns=("id",),
            update_columns=("name",),
        )

        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("ON CONFLICT (id) DO UPDATE", sql)
        self.assertIn("excluded.name", sql)

    def test_builds_mysql_duplicate_key_statement(self) -> None:
        statement = upsert_statement(
            self.session_for(mysql.dialect()),
            self.table,
            [{"id": 1, "name": "brick"}],
            conflict_columns=("id",),
            update_columns=("name",),
        )

        sql = str(statement.compile(dialect=mysql.dialect()))
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)


if __name__ == "__main__":
    unittest.main()
