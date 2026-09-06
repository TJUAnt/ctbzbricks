"""Preview Storage RLS 必须与拆分后的 Star/Watch 产品语义一致。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260905_0025_component_preview_policy_star_watch_split.py"
)


def test_upgrade_allows_only_owner_or_public_non_draft_preview(monkeypatch) -> None:
    """升级策略不得引用已删除关系，也不得让 Star/Watch 隐式扩大 Preview 权限。"""
    migration = load_migration()
    executed: list[str] = []

    monkeypatch.setattr(migration, "_storage_objects_exist", lambda: True)
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    sql = "\n".join(executed).lower()
    assert "component.owner_id = auth.uid()" in sql
    assert "component.status = 'active'" in sql
    assert "version.status <> 'draft'" in sql
    assert "artifact.verification_status = 'verified'" in sql
    assert "component_repo.component_subscriptions" not in sql
    assert "component_repo.component_stars" not in sql
    assert "component_watch_periods" not in sql
    assert "public.component_subscriptions" not in sql


def test_downgrade_uses_post_split_star_relation_instead_of_deleted_table(monkeypatch) -> None:
    """回滚可以恢复旧授权语义，但仍必须在当前 Goose schema 上可执行。"""
    migration = load_migration()
    executed: list[str] = []

    monkeypatch.setattr(migration, "_storage_objects_exist", lambda: True)
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.downgrade()

    sql = "\n".join(executed).lower()
    assert "component_repo.component_stars" in sql
    assert "component_repo.component_subscriptions" not in sql
    assert "public.component_subscriptions" in sql


def load_migration() -> ModuleType:
    """按独立模块加载迁移，避免测试依赖 Alembic revision import 顺序。"""
    spec = importlib.util.spec_from_file_location(
        "component_preview_policy_star_watch_split_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
