"""Alembic migration integration tests against a legacy SQLite schema."""

from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_schema_alignment_upgrades_legacy_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "legacy.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    engine = create_engine(database_url)
    create_legacy_schema(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("prepend_sys_path", str(BACKEND_ROOT))
    command.upgrade(config, "head")

    assert current_revision(engine) == "20260823_0024"
    assert_schema_columns_are_aligned(engine)
    assert_legacy_failures_are_structured(engine)
    assert {
        "component_groups",
        "component_group_memberships",
        "component_subscriptions",
    }.issubset(set(inspect(engine).get_table_names()))
    assert {"deleted_at", "deleted_by"}.issubset(
        {
            column["name"]
            for column in inspect(engine).get_columns("components")
        }
    )
    assert {
        "preview_artifact_id",
        "preview_status",
        "preview_generator_version",
        "preview_failure_code",
        "preview_failure_params_json",
    }.issubset(
        {
            column["name"]
            for column in inspect(engine).get_columns("component_versions")
        }
    )
    assert {"deleted_at", "deleted_by"}.issubset(
        {
            column["name"]
            for column in inspect(engine).get_columns("component_versions")
        }
    )


def create_legacy_schema(engine) -> None:
    statements = (
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)",
        (
            "INSERT INTO alembic_version (version_num) "
            "VALUES ('20260723_0013')"
        ),
        (
            "CREATE TABLE components "
            "(id VARCHAR(36) PRIMARY KEY)"
        ),
        (
            "CREATE TABLE component_versions ("
            "id VARCHAR(36) PRIMARY KEY, component_id VARCHAR(36) NOT NULL)"
        ),
        (
            "CREATE TABLE ldraw_files "
            "(id INTEGER PRIMARY KEY, parse_error TEXT NULL)"
        ),
        (
            "CREATE TABLE ldraw_file_references ("
            "id INTEGER PRIMARY KEY, ref_name VARCHAR(256) NOT NULL, "
            "resolve_error TEXT NULL)"
        ),
        (
            "INSERT INTO ldraw_file_references "
            "(id, ref_name, resolve_error) "
            "VALUES (1, 'missing.dat', 'private legacy details')"
        ),
        (
            "CREATE TABLE ldraw_shadow_files "
            "(id INTEGER PRIMARY KEY, parse_error TEXT NULL)"
        ),
        (
            "CREATE TABLE ldraw_shadow_meta_raw ("
            "id INTEGER PRIMARY KEY, line_no INTEGER NOT NULL, "
            "parse_error TEXT NULL)"
        ),
        (
            "INSERT INTO ldraw_shadow_meta_raw "
            "(id, line_no, parse_error) VALUES (1, 42, 'private details')"
        ),
        (
            "CREATE TABLE ldraw_shadow_includes "
            "(id INTEGER PRIMARY KEY, expand_error TEXT NULL)"
        ),
        (
            "CREATE TABLE pixel_art_projects "
            "(id VARCHAR(64) PRIMARY KEY, name VARCHAR(255) NOT NULL)"
        ),
        (
            "INSERT INTO pixel_art_projects (id, name) "
            "VALUES ('pixel-1', 'original name')"
        ),
        (
            "CREATE TABLE model_fitting_jobs ("
            "id VARCHAR(64) PRIMARY KEY, error_message TEXT NULL)"
        ),
        (
            "INSERT INTO model_fitting_jobs (id, error_message) "
            "VALUES ('job-1', 'private database details')"
        ),
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def current_revision(engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        )


def assert_schema_columns_are_aligned(engine) -> None:
    inspector = inspect(engine)
    expected = {
        "ldraw_files": {"parse_error_code", "parse_error_params_json"},
        "ldraw_file_references": {
            "resolve_error_code",
            "resolve_error_params_json",
        },
        "ldraw_shadow_files": {
            "parse_error_code",
            "parse_error_params_json",
        },
        "ldraw_shadow_meta_raw": {
            "parse_error_code",
            "parse_error_params_json",
        },
        "ldraw_shadow_includes": {
            "expand_error_code",
            "expand_error_params_json",
        },
        "pixel_art_projects": {"content_locale"},
        "model_fitting_jobs": {
            "locale",
            "timezone",
            "error_code",
            "error_params_json",
        },
    }
    for table_name, required_columns in expected.items():
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        assert required_columns.issubset(actual_columns)

    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT content_locale FROM pixel_art_projects "
                "WHERE id = 'pixel-1'"
            )
        ).scalar_one() == "zh-CN"
        assert connection.execute(
            text(
                "SELECT locale, timezone FROM model_fitting_jobs "
                "WHERE id = 'job-1'"
            )
        ).one() == ("zh-CN", "Asia/Shanghai")


def assert_legacy_failures_are_structured(engine) -> None:
    with engine.connect() as connection:
        reference = connection.execute(
            text(
                "SELECT resolve_error_code, resolve_error_params_json "
                "FROM ldraw_file_references WHERE id = 1"
            )
        ).one()
        shadow_meta = connection.execute(
            text(
                "SELECT parse_error_code, parse_error_params_json "
                "FROM ldraw_shadow_meta_raw WHERE id = 1"
            )
        ).one()
        model_fitting = connection.execute(
            text(
                "SELECT error_code, error_params_json "
                "FROM model_fitting_jobs WHERE id = 'job-1'"
            )
        ).one()

    assert reference[0] == "ldraw.reference_not_found"
    assert json.loads(reference[1]) == {"reference": "missing.dat"}
    assert "private legacy details" not in reference[1]
    assert shadow_meta[0] == "ldraw.shadow.meta_parse_failed"
    assert json.loads(shadow_meta[1]) == {"line": 42}
    assert "private details" not in shadow_meta[1]
    assert model_fitting[0] == "model_fitting.create_failed"
    assert json.loads(model_fitting[1]) == {}
    assert "private database details" not in model_fitting[1]
