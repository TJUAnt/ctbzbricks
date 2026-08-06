"""Authenticated API contract tests for Component library groups."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.errors import install_error_handlers
from src.api.routes.component_repo import create_component_repo_router
from src.auth.current_user import CurrentUser, optional_current_user
from src.component_repo.services import ensure_component_repo_tables
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.model.models import Component


def test_group_api_requires_auth_and_scopes_tree_to_current_user() -> None:
    config = load_json_config("component_repo.json", REQUIRED_COMPONENT_REPO_CONFIG_KEYS)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_component_repo_tables(engine)
    with Session(engine) as session:
        session.add(component("mine", "user-a"))
        session.commit()

    app = FastAPI()
    install_error_handlers(app)
    app.state.db_engine = engine
    app.include_router(create_component_repo_router(config))

    anonymous = TestClient(app)
    response = anonymous.get(config["routes"]["component_groups"])
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.authentication_required"
    anonymous_search = anonymous.post(
        config["routes"]["component_group_component_search"].format(
            group_id="private-group",
        ),
        json={"contentLocale": "en-US", "query": "mine"},
    )
    assert anonymous_search.status_code == 401
    assert anonymous_search.json()["error"]["code"] == "auth.authentication_required"

    app.dependency_overrides[optional_current_user] = lambda: CurrentUser(
        user_id="user-a",
        email=None,
        role="authenticated",
        access_token="test-token",
        raw={},
    )
    client = TestClient(app)
    tree_response = client.get(config["routes"]["component_groups"])
    assert tree_response.status_code == 200
    root = tree_response.json()["root"]
    assert root["groupType"] == "root"
    assert root["name"] is None
    assert root["directComponentCount"] == 1

    create_response = client.post(
        config["routes"]["component_groups"],
        json={
            "parentGroupId": root["id"],
            "name": "Favorites",
            "contentLocale": "en-US",
        },
    )
    assert create_response.status_code == 201
    group_id = create_response.json()["id"]
    parent_response = client.post(
        config["routes"]["component_groups"],
        json={
            "parentGroupId": root["id"],
            "name": "Parent",
            "contentLocale": "en-US",
        },
    )
    assert parent_response.status_code == 201
    parent_id = parent_response.json()["id"]
    move_response = client.post(
        config["routes"]["component_group_move"].format(group_id=group_id),
        json={"parentGroupId": parent_id, "position": 0},
    )
    assert move_response.status_code == 200
    assert move_response.json()["parentGroupId"] == parent_id

    membership_response = client.put(
        config["routes"]["component_group_component"].format(
            group_id=group_id,
            component_id="mine",
        )
    )
    assert membership_response.status_code == 204
    components_response = client.get(
        config["routes"]["component_group_components"].format(group_id=group_id),
        params={"contentLocale": "en-US"},
    )
    assert components_response.status_code == 200
    assert [row["id"] for row in components_response.json()] == ["mine"]
    assert components_response.json()[0]["logicalSize"] == {
        "widthStud": 4.0,
        "depthStud": 6.0,
        "heightPlate": 3.0,
    }
    search_response = client.post(
        config["routes"]["component_group_component_search"].format(
            group_id=group_id,
        ),
        json={
            "contentLocale": "en-US",
            "query": "6x4 min",
            "statuses": ["active"],
            "allowPlanarRotation": True,
            "sizeTolerance": 0,
            "page": 1,
            "pageSize": 20,
        },
    )
    assert search_response.status_code == 200
    assert [row["id"] for row in search_response.json()["items"]] == ["mine"]
    assert search_response.json()["statusCounts"] == {"active": 1}


def component(component_id: str, owner_id: str) -> Component:
    now = datetime.now(timezone.utc)
    return Component(
        id=component_id,
        name=component_id,
        content_kind="user",
        content_locale="en-US",
        category=None,
        status="active",
        current_version_id=None,
        logical_width_stud=4,
        logical_depth_stud=6,
        logical_height_plate=3,
        description=None,
        tags_json=[],
        metadata_json={},
        created_by=f"auth:{owner_id}",
        created_at=now,
        updated_at=now,
    )
