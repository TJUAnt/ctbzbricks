"""防止已经删除的 Python Component Repo 公共入口在 G8 后被重新引入。"""

from __future__ import annotations

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def test_fastapi_component_repo_router_and_dto_are_removed() -> None:
    """Component Repo 公共 API 必须只由 Go 提供，Python 不再保留第二套路由或 DTO。"""

    assert not (BACKEND_ROOT / "src/api/routes/component_repo.py").exists()
    assert not (BACKEND_ROOT / "src/api/schemas/component_repo.py").exists()

    main_source = (BACKEND_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    for forbidden in (
        "create_component_repo_router",
        "component_import_executor",
        "component_import_futures",
    ):
        assert forbidden not in main_source


def test_fastapi_config_has_no_legacy_component_public_routes() -> None:
    """共享 Python 配置可继续服务其他领域，但不能重新声明旧 Component 公共路径。"""

    config = json.loads(
        (BACKEND_ROOT / "config/component_repo.json").read_text(encoding="utf-8")
    )
    route_paths = tuple(config["routes"].values())
    forbidden_prefixes = (
        "/api/components",
        "/api/component-",
    )
    assert all(
        not path.startswith(forbidden_prefixes)
        for path in route_paths
    )

    domain_router = (
        BACKEND_ROOT / "src/api/routes/domain_content.py"
    ).read_text(encoding="utf-8")
    assert "component_translation" not in domain_router
    assert "upsert_component_translation" not in domain_router
