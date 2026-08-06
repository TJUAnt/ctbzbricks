"""Domain tests for per-user Component library groups."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.errors import DomainError
from src.component_repo.group_service import (
    add_component_to_group,
    create_group,
    delete_group,
    list_component_group_ids,
    list_group_components,
    list_group_tree,
    move_group,
    search_group_components,
    subscribe_component,
    unsubscribe_component,
    update_group,
)
from src.component_repo.services import ensure_component_repo_tables
from src.model.models import Component, ComponentGroup, ComponentTranslation


USER_A = "user-a"
USER_B = "user-b"


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_component_repo_tables(value)
    with Session(value) as session:
        session.add_all(
            [
                component("owned-active", USER_A, "active"),
                component("owned-draft", USER_A, "draft"),
                component("other-active", USER_B, "active"),
                component("other-archived", USER_B, "archived"),
            ]
        )
        session.commit()
    return value


def test_root_lists_owned_and_active_subscribed_components(engine) -> None:
    subscribe_component(engine, USER_A, "other-active")
    tree = list_group_tree(engine, USER_A)

    rows = list_group_components(engine, USER_A, tree["root"]["id"], "zh-CN")

    assert {row["id"] for row in rows} == {
        "owned-active",
        "owned-draft",
        "other-active",
    }
    assert tree["root"]["name"] is None
    assert tree["root"]["directComponentCount"] == 3

    with pytest.raises(DomainError) as error:
        subscribe_component(engine, USER_A, "other-archived")
    assert error.value.code == "component_repo.subscription_component_unavailable"


def test_component_can_belong_to_multiple_direct_groups(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    first = create_group(engine, USER_A, tree["root"]["id"], "Vehicles", "en-US")
    second = create_group(engine, USER_A, tree["root"]["id"], "Favorites", "en-US")

    add_component_to_group(engine, USER_A, first["id"], "owned-active")
    add_component_to_group(engine, USER_A, second["id"], "owned-active")

    assert set(list_component_group_ids(engine, USER_A, "owned-active")) == {
        first["id"],
        second["id"],
    }
    assert [row["id"] for row in list_group_components(engine, USER_A, first["id"], "en-US")] == [
        "owned-active"
    ]


def test_group_component_size_is_null_when_any_dimension_is_missing(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    with Session(engine) as session:
        component_row = session.get(Component, "owned-active")
        assert component_row is not None
        component_row.logical_width_stud = 4
        component_row.logical_depth_stud = 6
        component_row.logical_height_plate = None
        session.commit()

    rows = list_group_components(engine, USER_A, tree["root"]["id"], "en-US")
    owned = next(row for row in rows if row["id"] == "owned-active")

    assert owned["logicalSize"] is None


def test_search_matches_fuzzy_name_and_planar_rotated_dimensions(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    with Session(engine) as session:
        component_row = session.get(Component, "owned-active")
        assert component_row is not None
        component_row.name = "Wheel module"
        component_row.logical_width_stud = 4
        component_row.logical_depth_stud = 6
        component_row.logical_height_plate = 3
        session.commit()

    result = search_group_components(
        engine,
        USER_A,
        tree["root"]["id"],
        "en-US",
        "6x4x3 whel",
        None,
        True,
        0,
        1,
        20,
    )
    wrong_height = search_group_components(
        engine,
        USER_A,
        tree["root"]["id"],
        "en-US",
        "6x3x4 wheel",
        None,
        True,
        0,
        1,
        20,
    )

    assert [row["id"] for row in result["items"]] == ["owned-active"]
    assert wrong_height["total"] == 0


def test_search_matches_displayed_9x16_size_despite_geometry_float_noise(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    with Session(engine) as session:
        component_row = session.get(Component, "owned-active")
        assert component_row is not None
        component_row.logical_width_stud = 8.996
        component_row.logical_depth_stud = 16.004
        component_row.logical_height_plate = 12.5
        session.commit()

    result = search_group_components(
        engine,
        USER_A,
        tree["root"]["id"],
        "en-US",
        "9x16",
        None,
        True,
        0,
        1,
        20,
    )

    assert [row["id"] for row in result["items"]] == ["owned-active"]


def test_search_accepts_spaces_in_dimension_and_ignores_height_for_2d_query(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    with Session(engine) as session:
        component_row = session.get(Component, "owned-active")
        assert component_row is not None
        component_row.logical_width_stud = 9
        component_row.logical_depth_stud = 16
        component_row.logical_height_plate = None
        session.commit()

    result = search_group_components(
        engine,
        USER_A,
        tree["root"]["id"],
        "en-US",
        "9 x 16",
        None,
        True,
        0,
        1,
        20,
    )

    assert [row["id"] for row in result["items"]] == ["owned-active"]


def test_search_uses_reviewed_name_for_requested_locale(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    with Session(engine) as session:
        row = component("official-car", USER_A, "active")
        row.name = "Roadster"
        row.content_kind = "official"
        session.add(row)
        session.flush()
        session.add(
            ComponentTranslation(
                component_id=row.id,
                locale="zh-CN",
                name="跑车组件",
                description=None,
                tags_json=[],
                translation_status="reviewed",
                reviewed_by="reviewer",
                reviewed_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    translated = search_group_components(
        engine,
        USER_A,
        tree["root"]["id"],
        "zh-CN",
        "跑车",
        None,
        True,
        0,
        1,
        20,
    )
    source_locale = search_group_components(
        engine,
        USER_A,
        tree["root"]["id"],
        "en-US",
        "跑车",
        None,
        True,
        0,
        1,
        20,
    )

    assert translated["items"][0]["name"] == "跑车组件"
    assert source_locale["total"] == 0


def test_search_paginates_and_returns_unfiltered_status_counts(engine) -> None:
    tree = list_group_tree(engine, USER_A)

    result = search_group_components(
        engine,
        USER_A,
        tree["root"]["id"],
        "en-US",
        "",
        ["active"],
        True,
        0,
        1,
        1,
    )

    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["totalPages"] == 1
    assert result["statusCounts"] == {"active": 1, "draft": 1}


def test_groups_are_isolated_and_root_is_immutable(engine) -> None:
    tree_a = list_group_tree(engine, USER_A)
    tree_b = list_group_tree(engine, USER_B)
    group = create_group(engine, USER_A, tree_a["root"]["id"], "Private", "en-US")

    with pytest.raises(DomainError) as hidden:
        list_group_components(engine, USER_B, group["id"], "en-US")
    assert hidden.value.code == "component_repo.group_not_found"

    with pytest.raises(DomainError) as immutable:
        delete_group(engine, USER_A, tree_a["root"]["id"])
    assert immutable.value.code == "component_repo.group_root_immutable"
    assert tree_a["root"]["id"] != tree_b["root"]["id"]


def test_move_rejects_cycles_and_delete_cascades_subtree(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    parent = create_group(engine, USER_A, tree["root"]["id"], "Parent", "en-US")
    child = create_group(engine, USER_A, parent["id"], "Child", "en-US")
    add_component_to_group(engine, USER_A, child["id"], "owned-active")

    with pytest.raises(DomainError) as cycle:
        update_group(engine, USER_A, parent["id"], parent_group_id=child["id"])
    assert cycle.value.code == "component_repo.group_cycle"

    delete_group(engine, USER_A, parent["id"])
    with Session(engine) as session:
        assert session.scalar(
            select(ComponentGroup.id).where(ComponentGroup.id == child["id"])
        ) is None


def test_drag_move_reparents_and_normalizes_sibling_positions(engine) -> None:
    tree = list_group_tree(engine, USER_A)
    first = create_group(engine, USER_A, tree["root"]["id"], "First", "en-US")
    second = create_group(engine, USER_A, tree["root"]["id"], "Second", "en-US")
    parent = create_group(engine, USER_A, tree["root"]["id"], "Parent", "en-US")

    move_group(engine, USER_A, second["id"], parent["id"], 0)
    move_group(engine, USER_A, first["id"], parent["id"], 0)

    refreshed = list_group_tree(engine, USER_A)
    children = sorted(
        [
            group
            for group in refreshed["groups"]
            if group["parentGroupId"] == parent["id"]
        ],
        key=lambda group: group["sortOrder"],
    )
    assert [group["id"] for group in children] == [first["id"], second["id"]]
    assert [group["sortOrder"] for group in children] == [0, 1]


def test_unsubscribe_removes_only_that_users_group_memberships(engine) -> None:
    subscribe_component(engine, USER_A, "other-active")
    tree = list_group_tree(engine, USER_A)
    group = create_group(engine, USER_A, tree["root"]["id"], "Subscribed", "en-US")
    add_component_to_group(engine, USER_A, group["id"], "other-active")

    unsubscribe_component(engine, USER_A, "other-active")

    assert list_component_group_ids_raises(engine, USER_A, "other-active")
    assert list_group_components(engine, USER_A, group["id"], "en-US") == []


def test_archived_subscription_is_hidden_from_custom_groups(engine) -> None:
    subscribe_component(engine, USER_A, "other-active")
    tree = list_group_tree(engine, USER_A)
    group = create_group(engine, USER_A, tree["root"]["id"], "Subscribed", "en-US")
    add_component_to_group(engine, USER_A, group["id"], "other-active")
    with Session(engine) as session:
        row = session.get(Component, "other-active")
        assert row is not None
        row.status = "archived"
        session.commit()

    assert list_group_components(engine, USER_A, group["id"], "en-US") == []
    refreshed = list_group_tree(engine, USER_A)
    assert refreshed["groups"][0]["directComponentCount"] == 0


def list_component_group_ids_raises(engine, user_id: str, component_id: str) -> bool:
    with pytest.raises(DomainError) as error:
        list_component_group_ids(engine, user_id, component_id)
    assert error.value.code == "component_repo.component_not_managed"
    return True


def component(component_id: str, owner_id: str, status: str) -> Component:
    now = datetime.now(timezone.utc)
    return Component(
        id=component_id,
        name=component_id,
        content_kind="user",
        content_locale="en-US",
        category=None,
        status=status,
        current_version_id=None,
        description=None,
        tags_json=[],
        metadata_json={},
        created_by=f"auth:{owner_id}",
        created_at=now,
        updated_at=now,
    )
