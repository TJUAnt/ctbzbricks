"""Database revision contract tests."""

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.services.database_schema_service import (
    DatabaseSchemaError,
    EXPECTED_DATABASE_REVISION,
    validate_database_revision,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_database_revision_accepts_the_build_revision() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": EXPECTED_DATABASE_REVISION},
        )

    validate_database_revision(engine)


def test_database_revision_rejects_missing_version_table() -> None:
    engine = create_engine("sqlite://")

    with pytest.raises(
        DatabaseSchemaError,
        match="database.schema_revision_unavailable",
    ):
        validate_database_revision(engine)


def test_database_revision_rejects_other_or_multiple_heads() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES ('older'), ('other-head')"
            )
        )

    with pytest.raises(
        DatabaseSchemaError,
        match=(
            "database.schema_revision_mismatch "
            f"expected={EXPECTED_DATABASE_REVISION} "
            "actual=older,other-head"
        ),
    ):
        validate_database_revision(engine)


def test_api_main_has_no_schema_mutation_calls() -> None:
    main_path = BACKEND_ROOT / "src" / "api" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    called_names = {
        function_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }

    assert "validate_database_revision" in called_names
    assert not {
        name
        for name in called_names
        if name.startswith("ensure_")
        or name in {"create_all", "create", "drop_all", "drop"}
    }


def function_name(function: ast.expr) -> str:
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""
