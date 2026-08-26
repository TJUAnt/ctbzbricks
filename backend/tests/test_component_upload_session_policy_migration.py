"""Storage INSERT policy must authorize only API-issued pending upload keys."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260823_0024_component_upload_session_insert_policy.py"
)


def test_upgrade_binds_insert_to_pending_upload_session(monkeypatch) -> None:
    migration = load_migration()
    executed: list[str] = []

    monkeypatch.setattr(migration, "_storage_objects_exist", lambda: True)
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    sql = "\n".join(executed).lower()
    assert "component_repo.upload_session_files" in sql
    assert "component_repo.upload_sessions" in sql
    assert "upload_file.storage_key = object_name" in sql
    assert "upload_file.status = 'pending'" in sql
    assert "upload_session.owner_id = auth.uid()" in sql
    assert "upload_session.status = 'pending'" in sql
    assert "upload_session.expires_at > now()" in sql
    assert "public.can_upload_component_session_file(name)" in sql


def test_downgrade_restores_owner_prefix_insert_policy(monkeypatch) -> None:
    migration = load_migration()
    executed: list[str] = []

    monkeypatch.setattr(migration, "_storage_objects_exist", lambda: True)
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.downgrade()

    sql = "\n".join(executed).lower()
    assert "storage.foldername(name)" in sql
    assert "drop function if exists public.can_upload_component_session_file(text)" in sql


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "component_upload_session_policy_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
