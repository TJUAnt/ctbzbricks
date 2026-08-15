"""Storage policy ownership contract for server-side Artifact cleanup."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260809_0022_component_storage_server_cleanup.py"
)


def test_upgrade_removes_authenticated_delete_policy(monkeypatch) -> None:
    migration = load_migration()
    executed: list[str] = []

    monkeypatch.setattr(migration, "_storage_objects_exist", lambda: True)
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    assert executed == [
        'drop policy if exists "component artifacts authenticated delete" '
        "on storage.objects"
    ]


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "component_storage_server_cleanup_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
